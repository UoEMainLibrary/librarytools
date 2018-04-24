#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""subjectify.py: A tool to retrieve DDC/LCC identifiers from OCLC's Classify API

Version: 1.0
Author: Mike Bennett <mike.bennett@ed.ac.uk>

Subjectify takes a CSV containing ISBN/ISSNs, and optionally Author/Title data and
performs a series of lookups against the OCLC Classify2 API to retrieve Dewey Decimal
and Library of Congress subject classifiers for each item, writing the results to a
new CSV file.

Usage: 'subjectify.py infile.csv outfile.csv'
"""

import sys, os, csv, requests
import xml.etree.ElementTree as ET

endpoint_url = "http://classify.oclc.org/classify2/Classify" # OCLC Classify API URL
base_querystring = "?summary=true&maxRecs=1"
ns = {"classify": "http://classify.oclc.org"} # xml namespace
fields = ["id","isbn","issn","author","title","ddc","lcc"] # csv fields
records_in = [] # state data
records_out = [] # state data

def load_data(infile):
    """Read a CSV file into the state object and return count of loaded records"""
    # Make sure file exists
    if not os.path.isfile(infile): sys.exit("Fatal Error: Input file does not exist!")
    # Attempt to open and read file
    try:
        with open(infile, "r") as csvfile:
            reader = csv.DictReader(csvfile, fieldnames=fields, restval=None)
            count = 0
            for row in reader:
                records_in.append(row)
                count += 1
        return count
    except:
        return 0


def write_data(outfile):
    """Write the data in the state object to file and return boolean success indicator"""
    try:
        with open(outfile, "w") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fields)
            #writer.writeheader()
            writer.writerows(records_out)
            return True
    except:
        return False

def get_tree(xmldata):
    """Takes string or ET and returns an ET"""
    if type(xmldata) == str:
        try:
            return ET.fromstring(xmldata)
        except:
            return None
    elif type(xmldata) == ET.Element:
        return xmldata
    else:
        return None

def oclc_search(searchtype, data):
    """Query OCLC endpoint

    Valid searchtype values:
        isbn (Either ISBN10 or ISBN13 identifier)
        issn (ISSN-L preferred but p-ISSN or e-ISSN will work)
        bib  (Use Author/Title data)
        wi   (OCLC "work index" identifier)

    Data should be either a string object for ISBN/ISSN/WI or
    a two-value string tuple of (<author>, <name>) as appropriate.

    Returns one of:
        A string of XML data on successful query
        Boolean False on invalid searchtype or data
        None object in event of error making request
    """

    # Basic sanity checks and query forming
    if searchtype in ['isbn', 'issn', 'wi']:
        if type(data) != str: return False
        query = "%s=%s" % (searchtype, data)
    elif searchtype == "bib":
        if type(data) != tuple: return False
        if len(data) != 2: return False
        author, title = data
        query = "author=\"%s\"&title=\"%s\"" % (author, title)
    else:
        # invalid searchtype
        return False

    request_url = endpoint_url + base_querystring + "&" + query

    try:
        response = requests.get(request_url)
        if response.status_code == 200:
            return response.content
        else:
            return None
    except:
        return None

def extract_response(record_xml):
    """Parse an OCLC Classify XML record, extract and return the response code

    Possible responses:
    0:    Success. Single-work summary response provided.
    2:    Success. Single-work detail response provided.
    4:    Success. Multi-work response provided.
    100:  No input. The method requires an input argument.
    101:  Invalid input. The standard number argument is invalid.
    102:  Not found. No data found for the input argument.
    200:  Unexpected error.
    (Source: http://classify.oclc.org/classify2/api_docs/classify.html)
    """
    tree = get_tree(record_xml)
    if tree is None:
        return None

    response_code = tree.find("classify:response", ns)
    if response_code is None:
        # Uh-oh!
        return None
    else:
        return int(response_code.attrib["code"])

def extract_ids(record_xml):
    """Parse an OCLC Classify XML record for a single work and extract DDC/LLC and the Work Identifier (wi)
    Takes a String or XML ETree object and returns a tuple of strings (<ddc id>, <llc id>) or None
    """
    tree = get_tree(record_xml)
    if tree is None:
        return None

    # Check OCLC response code is for a single work record
    # 0:    Success. Single-work summary response provided.
    # 2:    Success. Single-work detail response provided.
    code = extract_response(tree)
    if code not in [0, 2]:
        return None
    else:
        ddc = tree.find("classify:recommendations/classify:ddc/classify:mostPopular",ns).attrib["nsfa"]
        lcc = tree.find("classify:recommendations/classify:lcc/classify:mostPopular",ns).attrib["nsfa"]
        return (ddc, lcc)

def resolve_multiple(record_xml):
    """Parse an OCLC Classify XML record for a multiple-work response, extract and return the Work Identifier (wi)"""

    tree = get_tree(record_xml)
    if tree is None:
        return None

    # Check OCLC response code is for a multi record
    # 4:    Success. Multi-work response provided.
    code = extract_response(tree)
    if code != 4:
        return None
    else:
        wi = tree.find("classify:works/classify:work[0]", ns).attrib["wi"]
        return wi

def process_row(row):
    """Process a row from the csv file. Main per-record logic"""

    # Determine whether we are matching against ISBN/ISSN or bibliographic data
    # Start from least preferable and check each type, keeping current best in state variable
    search_type = None
    data = None

    if row["author"] != "" and row["title"] != "":
        search_type = "bib"
        data = (row["author"], row["title"])
    if row["issn"] != "":
        search_type = "issn"
        data = row["issn"]
    if row["isbn"] != "":
        search_type = "isbn"
        data = row["isbn"]

    if search_type is None:
        return None
    # Make the first query and check the status
    record = oclc_search(search_type, data)
    status = extract_response(record)

    if status is None or status >= 100:
        # Error or no input
        return None
    elif status in [0,2]:
        # Single work record, go to extraction
        row["ddc"], row["lcc"] = extract_ids(record)
        return row

    elif status == 4:
        # Multi-work record, attempt to resolve
        wi = resolve_multiple(record)
        if wi:
            parent_record = oclc_search("wi", wi)
            parent_status = extract_response(parent_record)
            if parent_status in [0, 2]:
                # Resolved, extract the IDs
                row["ddc"], row["lcc"] = extract_ids(parent_record)
                return row
            else:
                return None


if __name__ == '__main__':
    if len(sys.argv) < 3:
        sys.exit("Not enough arguments! Usage: subjectify.py infile.csv outfile.csv")

    print("""
    subjectify.py: A tool to retrieve DDC/LCC identifiers from OCLC's Classify API
    ==============================================================================
    
    """)

    infile = sys.argv[1]
    outfile = sys.argv[2]

    print("Loading data from %s" % infile)
    count = load_data(infile)
    print("Loaded %s records" % count)

    for row in records_in:
        print("Processing record %s" % row["id"])
        row_out = process_row(row)
        records_out.append(row)

    print("Finished processing, writing to file %s" % outfile)
    write_data(outfile)

    print("Done, goodbye!")