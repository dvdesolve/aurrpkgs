#!/usr/bin/env python3

import argparse
import json
import re
import sys
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


# handle non-ok requests
class RequestError(Exception):
    def __init__(self, status, reason):
        self.status = status
        self.reason = reason

# handle bad API responses
class APIResponseError(Exception):
    def __init__(self, reason):
        self.reason = reason

# handle unsuccessful CRAN searches
class CRANSearchError(Exception):
    def __init__(self, reason):
        self.reason = reason


# error codes
ERR_request = 1
ERR_api_response = 2
ERR_server = 3
ERR_network = 4
ERR_cran = 5


# some defaults
API_url = "https://aur.archlinux.org/rpc/"
API_version = 5


# get command line options
parser = argparse.ArgumentParser(description = "Tool for easy management of AUR R packages")
parser.add_argument("user", help = "AUR username")
cmdline_args = vars(parser.parse_args())

username = cmdline_args["user"]


# request for R packages
query_params = {
        "v": API_version,
        "type": "search",
        "by": "maintainer",
        "arg": username
}

query_string = urlencode(query_params)
query_url = "?".join([API_url, query_string])

try:
    with urlopen(query_url) as response:
        if response.status != 200:
            raise RequestError(response.status, response.reason)

        response_json = json.load(response)

        if response_json["type"] != "search":
            raise APIResponseError("response type is invalid")

        if response_json["resultcount"] == 0:
            raise APIResponseError("no R packages for user " + username + " were found in AUR")
except HTTPError as err:
    print("Something wrong with AUR API request; server returned", err.code)
    sys.exit(ERR_server)
except URLError as err:
    print("Error while trying to connect to the AUR:", err.reason)
    sys.exit(ERR_network)
except RequestError as err:
    print("Error while fetching request:", err.status, err.reason)
    sys.exit(ERR_request)
except APIResponseError as err:
    print("Error while processing API response:", err.reason)
    sys.exit(ERR_api_response)


# filter out any non-R packages
pkglist = [i for i in response_json["results"] if i["Name"].startswith("r-")]


# check for updates
all_updated = True
mandatory_keys = ["Name", "Version", "URL"]

for i in range(len(pkglist)):
    # leave only necessary keys
    pkglist[i] = {k: v for k, v in pkglist[i].items() if k in mandatory_keys}

    # strip '-pkgrel'
    pkglist[i]["Version"] = pkglist[i]["Version"].split('-', 1)[0]

    # get version info from CRAN
    try:
        with urlopen(pkglist[i]["URL"]) as response:
            html = response.read().decode("utf-8")
            table_pattern = re.compile(r"<table summary=\"Package(.*?) summary\">(.*?)</table>", flags = re.DOTALL)
            table_match = table_pattern.search(html)

            if table_match:
                html = table_match.group(2)
                version_pattern = re.compile(r"<tr>\n<td>Version:</td>\n<td>(.*?)</td>\n</tr>", flags = re.DOTALL)
                version_match = version_pattern.search(html)

                if version_match:
                    pkglist[i]["CRANVer"] = version_match.group(1)

                    # make CRANVersion to conform with Arch standards (https://wiki.archlinux.org/index.php/R_package_guidelines)
                    pkglist[i]["CRANVersion"] = re.sub(r"[:-]", ".", pkglist[i]["CRANVer"])
                else:
                    raise CRANSearchError("can't find version info")
            else:
                raise CRANSearchError("can't find summary table")

    except HTTPError as err:
        print("Something wrong with CRAN database request; server returned", err.code)
        sys.exit(ERR_server)
    except URLError as err:
        print("Error while trying to connect:", err.reason)
        sys.exit(ERR_network)
    except RequestError as err:
        print("Error while fetching request:", err.status, err.reason)
        sys.exit(ERR_request)
    except CRANSearchError as err:
        print("Error while processing CRAN database:", err.reason)
        sys.exit(ERR_cran)

    aurver = [int(x) for x in pkglist[i]["Version"].split(".")]
    cranver = [int(x) for x in pkglist[i]["CRANVersion"].split(".")]

    if aurver < cranver:
        all_updated = False
        print("Package", pkglist[i]["Name"], "is outdated:", pkglist[i]["Version"], "(AUR) vs", pkglist[i]["CRANVer"], "(CRAN)")


# print summary if all is good
if all_updated:
    print("All AUR R packages of user", username, "are up-to-date")


sys.exit(0)
