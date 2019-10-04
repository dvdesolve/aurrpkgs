#!/usr/bin/env python3

import argparse
import json
import re
import sys
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlparse
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
class RepoSearchError(Exception):
    def __init__(self, reason):
        self.reason = reason


# error codes
ERR_request = 1
ERR_api_response = 2
ERR_server = 3
ERR_network = 4


# some defaults
API_url = "https://aur.archlinux.org/rpc/"
API_version = 5
CRAN_domain = "cran.r-project.org"
script_version = "0.1.0"


# get command line options
parser = argparse.ArgumentParser(description = "Tool for easy management of AUR R packages")
parser.add_argument("user", help = "AUR username")
parser.add_argument("--version", action = "version", version = "%(prog)s " + script_version)
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

    # non-CRAN repositories are not supported yet
    if "{uri.netloc}".format(uri = urlparse(pkglist[i]["URL"])) != CRAN_domain:
        print("Skipping non-CRAN package", pkglist[i]["Name"])
        continue

    # get version info from repository
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
                    pkglist[i]["RepoVer"] = version_match.group(1)

                    # make RepoVersion to conform with Arch standards (https://wiki.archlinux.org/index.php/R_package_guidelines)
                    pkglist[i]["RepoVersion"] = re.sub(r"[:-]", ".", pkglist[i]["RepoVer"])
                else:
                    raise RepoSearchError("can't find version info")
            else:
                raise RepoSearchError("can't find package info")

    except HTTPError as err:
        print("Something wrong with repository request; server returned", err.code)
        print("Skipping package", pkglist[i]["Name"])
        continue
    except URLError as err:
        print("Error while trying to connect to repository:", err.reason)
        print("Skipping package", pkglist[i]["Name"])
        continue
    except RequestError as err:
        print("Error while fetching request from repository:", err.status, err.reason)
        print("Skipping package", pkglist[i]["Name"])
        continue
    except RepoSearchError as err:
        print("Error while processing repository info for package " + pkglist[i]["Name"] + ":", err.reason)
        print("Skipping package", pkglist[i]["Name"])
        continue

    aurver = [int(x) for x in pkglist[i]["Version"].split(".")]
    repover = [int(x) for x in pkglist[i]["RepoVersion"].split(".")]

    if aurver < repover:
        all_updated = False
        print("Package", pkglist[i]["Name"], "is outdated:", pkglist[i]["Version"], "(AUR) vs", pkglist[i]["RepoVer"], "(" + pkglist[i]["URL"] + ")")


# print summary if all is good
if all_updated:
    print("All AUR R packages of user", username, "are up-to-date")


sys.exit(0)
