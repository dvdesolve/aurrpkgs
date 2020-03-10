#!/usr/bin/env python3

""" Easy checking AUR R packages for updates """

import argparse
import json
import multiprocessing
import re
import sys
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen


class RequestError(Exception):
    """ handle non-ok network requests """

    def __init__(self, status, reason):
        self.status = status
        self.reason = reason

class APIRequestError(Exception):
    """ handle bad AUR API responses """

    def __init__(self, reason):
        self.reason = reason

class RepoSearchError(Exception):
    """ handle unsuccessful CRAN lookups """

    def __init__(self, reason):
        self.reason = reason

class APError:
    """ error codes """

    request = 1
    api_request = 2
    server = 3
    network = 4
    no_pkgs = 5

class APColor:
    """ color codes """

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

class APMsg:
    """ messages """

    skipping = ". " + APColor.yellow + "Skipping" + APColor.nc
    exiting = ". " + APColor.red + "Exiting" + APColor.nc

class APProgress:
    """ progress counter """

    def __init__(self, manager, initval=0):
        """ assign our own storage and lock instance """

        self.val = manager.Value('i', initval)
        self.lock = manager.RLock()

    def increment(self):
        """ just increment counter by 1 """

        with self.lock:
            self.val.value += 1

    @property
    def value(self):
        """ return integer value """
        with self.lock:
            return self.val.value


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

SCRIPT_VERSION = "0.1.5"
MANDATORY_KEYS = ["Name", "Version", "URL"]


def check_updates(packages, total, finished, output):
    """ check packages for updates """
    for package in packages:
        # print current progress
        with finished.lock:
            finished.increment()

            print("Processing package "
                  + APColor.data + str(finished.value) + APColor.nc + "/"
                  + APColor.data + str(total) + APColor.nc + "...",
                  end=("\r" if finished.value < total else " "))


        # leave only necessary keys
        package = {k: v for k, v in package.items() if k in MANDATORY_KEYS}

        # strip '-pkgrel' part and replace possible underscores with dots
        package["Version"] = re.sub(r"_", ".", package["Version"].split('-', 1)[0])

        # some repositories are not supported yet
        domain = "{uri.netloc}".format(uri=urlparse(package["URL"])).lower()

        if not any(r["url"] == domain for r in SUPPORTED_REPOS):
            output.append(APColor.warn + "[WARN]" + APColor.nc +
                          " Package " +
                          APColor.data + package["Name"] + APColor.nc +
                          ": repository " +
                          APColor.data + domain + APColor.nc +
                          " is unsupported (yet)" +
                          APMsg.skipping)

            continue

        repo = next(r for r in SUPPORTED_REPOS if r["url"] == domain)

        # get version info from repository
        try:
            with urlopen(package["URL"]) as response:
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
                        package["RepoVer"] = version_match.group(repo["version_match_index"])

                        # make RepoVersion to conform with Arch standards
                        # https://wiki.archlinux.org/index.php/R_package_guidelines
                        package["RepoVersion"] = re.sub(r"[:-]", ".", package["RepoVer"])
                    else:
                        raise RepoSearchError("can't find version info")
                else:
                    raise RepoSearchError("can't find package info")

        except HTTPError as err:
            output.append(APColor.warn + "[WARN]" + APColor.nc +
                          " Package " +
                          APColor.data + package["Name"] + APColor.nc +
                          ": error while doing repository request: server returned " +
                          APColor.data + str(err.code) + APColor.nc +
                          APMsg.skipping)
            continue

        except URLError as err:
            output.append(APColor.warn + "[WARN]" + APColor.nc +
                          " Package " +
                          APColor.data + package["Name"] + APColor.nc +
                          ": error while trying to connect to repository: " +
                          APColor.data + str(err.reason) + APColor.nc +
                          APMsg.skipping)
            continue

        except RequestError as err:
            output.append(APColor.warn + "[WARN]" + APColor.nc +
                          " Package " +
                          APColor.data + package["Name"] + APColor.nc +
                          ": error while fetching request data from repository: " +
                          APColor.data + str(err.status) + " " + str(err.reason) + APColor.nc +
                          APMsg.skipping)
            continue

        except RepoSearchError as err:
            output.append(APColor.warn + "[WARN]" + APColor.nc +
                          " Package " +
                          APColor.data + package["Name"] + APColor.nc +
                          ": error while processing repository response: " +
                          APColor.data + str(err.reason) + APColor.nc +
                          APMsg.skipping)
            continue

        aurver = [int(x) for x in package["Version"].split(".")]
        repover = [int(x) for x in package["RepoVersion"].split(".")]

        # compare versions in field-by-field way
        if aurver < repover:
            output.append(APColor.info + "[INFO]" + APColor.nc +
                          " Package " +
                          APColor.data + package["Name"] + APColor.nc +
                          " is outdated: " +
                          APColor.old + package["Version"] + APColor.nc +
                          " (AUR) vs " +
                          APColor.new + package["RepoVer"] + APColor.nc +
                          " (" + repo["name"] + ")")


def main():
    """ main routine """

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


    # we'll check for updates NOW!

    # use all available CPU cores
    num_proc = multiprocessing.cpu_count()
    mgr = multiprocessing.Manager()
    pool = multiprocessing.Pool(processes=num_proc)

    # calculate load per worker
    pkg_total = len(pkglist)
    pkgs_per_proc = pkg_total // num_proc

    # shared memory objects

    # we need that fucking workaround because multiprocessing.Manager()
    # doesn't provide get_lock() for Value objects
    finished = APProgress(mgr, 0)
    output_info = mgr.list()

    # load balancing
    for i in range(num_proc):
        start_i = i * pkgs_per_proc
        end_i = ((i + 1) * pkgs_per_proc) if i != (num_proc - 1) else None

        pool.apply_async(check_updates, (pkglist[start_i:end_i], pkg_total, finished, output_info))

    # wait for all guys
    pool.close()
    pool.join()

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


# main program starts here
if __name__ == "__main__":
    main()


sys.exit(0)
