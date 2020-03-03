#!/usr/bin/env python3
""" Main aurrpkgs script """

import argparse
import json
import re
import sys
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen


# handle non-ok requests
class RequestError(Exception):
    """ Handle request errors """
    def __init__(self, status, reason):
        self.status = status
        self.reason = reason

# handle bad API responses
class APIRequestError(Exception):
    """ Handle AUR API response errors """
    def __init__(self, reason):
        self.reason = reason

# handle unsuccessful CRAN searches
class RepoSearchError(Exception):
    """ Handle bad CRAN search requests """
    def __init__(self, reason):
        self.reason = reason

# error codes
class APError:
    """ Enum of error codes """
    request = 1
    api_request = 2
    server = 3
    network = 4
    no_pkgs = 5

# color codes
class APColor:
    """ Enum of color codes """
    red = "\033[1;31m"
    green = "\033[1;32m"
    yellow = "\033[1;33m"
    blue = "\033[1;34m"
    purple = "\033[1;35m"
    nc = "\033[0m"
    error = red
    ok = green
    warn = yellow
    info = purple
    data = blue
    old = red
    new = green

# messages
class APMsg:
    """ Enum of standard messages """
    skipping = ". " + APColor.yellow + "Skipping" + APColor.nc
    exiting = ". " + APColor.red + "Exiting" + APColor.nc


# some defaults
API_URL = "https://aur.archlinux.org/rpc/"
API_VERSION = 5

SUPPORTED_REPOS = [
    {
        "name": "CRAN",
        "url": "cran.r-project.org",
        "table_regex": r"<table summary=\"Package(.*?) summary\">(.*?)</table>",
        "table_match_index": 2,
        "version_regex": r"<tr>\n<td>Version:</td>\n<td>(.*?)</td>",
        "version_match_index": 1
    },

    {
        "name": "Bioconductor",
        "url": "bioconductor.org",
        "table_regex": r"<table class=\"details\">(.*?)</table>",
        "table_match_index": 1,
        "version_regex": r"<tr(.*?)>\n(\s*)<td>Version</td>\n(\s*)<td>(.*?)</td>",
        "version_match_index": 4
    }
]

SCRIPT_VERSION = "0.1.4"
MANDATORY_KEYS = ["Name", "Version", "URL"]


# get command line options
parser = argparse.ArgumentParser(description="Tool for easy management of AUR R packages")
parser.add_argument("user", help="AUR username")
parser.add_argument("--version", action="version", version="%(prog)s " + SCRIPT_VERSION)
cmdline_args = vars(parser.parse_args())

username = cmdline_args["user"]


# request for R packages
query_params = {
        "v": API_VERSION,
        "type": "search",
        "by": "maintainer",
        "arg": username
}

query_string = urlencode(query_params)
query_url = "?".join([API_URL, query_string])

try:
    with urlopen(query_url) as response:
        if response.status != 200:
            raise RequestError(response.status, response.reason)

        response_json = json.load(response)

        if response_json["type"] != "search":
            raise APIRequestError("response type " +
                                  APColor.data + response_json["type"] + APColor.nc +
                                  " is invalid")

        if response_json["resultcount"] == 0:
            raise APIRequestError("there are no packages for user " +
                                  APColor.data + username + APColor.nc +
                                  " in AUR")

except HTTPError as err:
    print(APColor.error + "[ERROR]" + APColor.nc,
          "Error while doing AUR API request: server returned",
          APColor.data + str(err.code) + APColor.nc + APMsg.exiting,
          file=sys.stderr)
    sys.exit(APError.server)

except URLError as err:
    print(APColor.error + "[ERROR]" + APColor.nc,
          "Error while trying to connect to the AUR:",
          APColor.data + str(err.reason) + APColor.nc + APMsg.exiting,
          file=sys.stderr)
    sys.exit(APError.network)

except RequestError as err:
    print(APColor.error + "[ERROR]" + APColor.nc,
          "Error while fetching request data: server returned",
          APColor.data + str(err.status) + " " + str(err.reason) + APColor.nc + APMsg.exiting,
          file=sys.stderr)
    sys.exit(APError.request)

except APIRequestError as err:
    print(APColor.error + "[ERROR]" + APColor.nc,
          "Error while processing AUR API response:",
          str(err.reason) + APMsg.exiting,
          file=sys.stderr)
    sys.exit(APError.api_request)


# filter out any non-R packages and VCS versions of R packages
pkglist = [i for i in response_json["results"] if i["Name"].startswith("r-") and not i["Name"].endswith("-git")]

if len(pkglist) == 0:
    print(APColor.error + "[ERROR]" + APColor.nc,
          "There are no R packages for user",
          APColor.data + username + APColor.nc, "in AUR" + APMsg.exiting,
          file=sys.stderr)
    sys.exit(APError.no_pkgs)


# check for updates
output_info = list()
pkg_num = len(pkglist)

for i in range(pkg_num):
    # print current progress
    print("Processing package "
          + APColor.data + str(i + 1) + APColor.nc + "/"
          + APColor.data + str(pkg_num) + APColor.nc + "...",
          end="\r" if i < (pkg_num - 1) else " ")

    # leave only necessary keys
    pkglist[i] = {k: v for k, v in pkglist[i].items() if k in MANDATORY_KEYS}

    # strip '-pkgrel' part and replace possible underscores with dots
    pkglist[i]["Version"] = re.sub(r"_", ".", pkglist[i]["Version"].split('-', 1)[0])

    # some repositories are not supported yet
    domain = "{uri.netloc}".format(uri=urlparse(pkglist[i]["URL"])).lower()

    if not any(r["url"] == domain for r in SUPPORTED_REPOS):
        output_info.append(APColor.warn + "[WARN]" + APColor.nc +
                           " Package " +
                           APColor.data + pkglist[i]["Name"] + APColor.nc +
                           ": repository " +
                           APColor.data + domain + APColor.nc +
                           " is unsupported (yet)" +
                           APMsg.skipping)

        continue

    repo = next(r for r in SUPPORTED_REPOS if r["url"] == domain)

    # get version info from repository
    try:
        with urlopen(pkglist[i]["URL"]) as response:
            html = response.read().decode("utf-8")

            table_regex = repo["table_regex"]
            table_pattern = re.compile(table_regex, flags=re.DOTALL)
            table_match = table_pattern.search(html)

            if table_match:
                # recheck
                html = table_match.group(repo["table_match_index"])

                version_regex = repo["version_regex"]
                version_pattern = re.compile(version_regex, flags=re.DOTALL)
                version_match = version_pattern.search(html)

                if version_match:
                    pkglist[i]["RepoVer"] = version_match.group(repo["version_match_index"])

                    # make RepoVersion to conform with Arch standards
                    # (https://wiki.archlinux.org/index.php/R_package_guidelines)
                    pkglist[i]["RepoVersion"] = re.sub(r"[:-]", ".", pkglist[i]["RepoVer"])
                else:
                    raise RepoSearchError("can't find version info")
            else:
                raise RepoSearchError("can't find package info")

    except HTTPError as err:
        output_info.append(APColor.warn + "[WARN]" + APColor.nc +
                           " Package " +
                           APColor.data + pkglist[i]["Name"] + APColor.nc +
                           ": error while doing repository request: server returned " +
                           APColor.data + str(err.code) + APColor.nc +
                           APMsg.skipping)
        continue

    except URLError as err:
        output_info.append(APColor.warn + "[WARN]" + APColor.nc +
                           " Package " +
                           APColor.data + pkglist[i]["Name"] + APColor.nc +
                           ": error while trying to connect to repository: " +
                           APColor.data + str(err.reason) + APColor.nc +
                           APMsg.skipping)
        continue

    except RequestError as err:
        output_info.append(APColor.warn + "[WARN]" + APColor.nc +
                           " Package " +
                           APColor.data + pkglist[i]["Name"] + APColor.nc +
                           ": error while fetching request data from repository: " +
                           APColor.data + str(err.status) + " " + str(err.reason) + APColor.nc +
                           APMsg.skipping)
        continue

    except RepoSearchError as err:
        output_info.append(APColor.warn + "[WARN]" + APColor.nc +
                           " Package " +
                           APColor.data + pkglist[i]["Name"] + APColor.nc +
                           ": error while processing repository response: " +
                           APColor.data + str(err.reason) + APColor.nc +
                           APMsg.skipping)
        continue

    aurver = [int(x) for x in pkglist[i]["Version"].split(".")]
    repover = [int(x) for x in pkglist[i]["RepoVersion"].split(".")]

    # compare versions in field-by-field way
    if aurver < repover:
        output_info.append(APColor.info + "[INFO]" + APColor.nc +
                           " Package " +
                           APColor.data + pkglist[i]["Name"] + APColor.nc +
                           " is outdated: " +
                           APColor.old + pkglist[i]["Version"] + APColor.nc +
                           " (AUR) vs " +
                           APColor.new + pkglist[i]["RepoVer"] + APColor.nc +
                           " (" + repo["name"] + ")")


# print summary
print(APColor.ok + "done" + APColor.nc)

if len(output_info) == 0:
    print(APColor.ok + "[OK]" + APColor.nc,
          "All AUR R packages of user",
          APColor.data + username + APColor.nc,
          "are up-to-date")
else:
    for line in output_info:
        print(line)


sys.exit(0)
