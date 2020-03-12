#!/usr/bin/env python3

""" Easy checking AUR R packages for updates """

## import necessary modules
import argparse
import json
import multiprocessing
import re
import sys
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen


## helper classes
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

    skipping = ". {}Skipping{}".format(APColor.yellow, APColor.nc)
    exiting = ". {}Exiting{}".format(APColor.red, APColor.nc)

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


## some defaults
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

SCRIPT_VERSION = "0.1.6"
MANDATORY_KEYS = ["Name", "Version", "URL"]


## helper functions
def check_updates(package):
    """ check updates for single package """

    # leave only necessary keys
    package = {k: v for k, v in package.items() if k in MANDATORY_KEYS}

    # strip '-pkgrel' part and replace possible underscores with dots
    package["Version"] = re.sub(r"_", ".", package["Version"].split('-', 1)[0])

    # some repositories are not supported yet
    domain = "{uri.netloc}".format(uri=urlparse(package["URL"])).lower()

    if not any(r["url"] == domain for r in SUPPORTED_REPOS):
        return "{}[WARN]{} Package {}{}{}: repository {}{}{} is unsupported (yet){}".format(
            APColor.warn, APColor.nc,
            APColor.data, package["Name"], APColor.nc,
            APColor.data, domain, APColor.nc,
            APMsg.skipping)

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
        return "{}[WARN]{} Package {}{}{}: error while doing repository request: server returned {}{}{}{}".format(
            APColor.warn, APColor.nc,
            APColor.data, package["Name"], APColor.nc,
            APColor.data, str(err.code), APColor.nc,
            APMsg.skipping)

    except URLError as err:
        return "{}[WARN]{} Package {}{}{}: error while trying to connect to repository: {}{}{}{}".format(
            APColor.warn, APColor.nc,
            APColor.data, package["Name"], APColor.nc,
            APColor.data, str(err.reason), APColor.nc,
            APMsg.skipping)

    except RequestError as err:
        return "{}[WARN]{} Package {}{}{}: error while fetching request data from repository: {}{} {}{}{}".format(
            APColor.warn, APColor.nc,
            APColor.data, package["Name"], APColor.nc,
            APColor.data, str(err.status), str(err.reason), APColor.nc,
            APMsg.skipping)

    except RepoSearchError as err:
        return "{}[WARN]{} Package {}{}{}: error while processing repository response: {}{}{}{}".format(
            APColor.warn, APColor.nc,
            APColor.data, package["Name"], APColor.nc,
            APColor.data, str(err.reason), APColor.nc,
            APMsg.skipping)

    # compare versions in field-by-field way
    aurver = [int(x) for x in package["Version"].split(".")]
    repover = [int(x) for x in package["RepoVersion"].split(".")]

    if aurver < repover:
        return "{}[INFO]{} Package {}{}{} is outdated: {}{}{} (AUR) vs {}{}{} ({})".format(
            APColor.info, APColor.nc,
            APColor.data, package["Name"], APColor.nc,
            APColor.old, package["Version"], APColor.nc,
            APColor.new, package["RepoVer"], APColor.nc, repo["name"])


def checker_worker(packages, total, finished, output):
    """ main worker function for parallel updates checking """

    for package in packages:
        # print current progress
        with finished.lock:
            finished.increment()

            print("{}[INFO]{} Processing package {}{}{}/{}{}{}...".format(
                APColor.info, APColor.nc,
                APColor.data, str(finished.value), APColor.nc,
                APColor.data, str(total), APColor.nc),
                  end=("\r" if finished.value < total else " "))

        # check package for updates
        res = check_updates(package)

        # store result (if any)
        if res:
            output.append(res)


def check_user(username):
    """ check packages of specific user """

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
                raise APIRequestError("response type {}{}{} is invalid".format(
                    APColor.data, response_json["type"], APColor.nc))

            if response_json["resultcount"] == 0:
                raise APIRequestError("there are no packages for user {}{}{} in AUR".format(
                    APColor.data, username, APColor.nc))

    except HTTPError as err:
        print("{}[ERROR]{} Error while doing AUR API request: server returned {}{}{}{}".format(
            APColor.error, APColor.nc,
            APColor.data, str(err.code), APColor.nc,
            APMsg.skipping))

        return

    except URLError as err:
        print("{}[ERROR]{} Error while trying to connect to the AUR: {}{}{}{}".format(
            APColor.error, APColor.nc,
            APColor.data, str(err.reason), APColor.nc,
            APMsg.skipping))

        return

    except RequestError as err:
        print("{}[ERROR]{} Error while fetching request data: server returned {}{} {}{}{}".format(
            APColor.error, APColor.nc,
            APColor.data, str(err.status), str(err.reason), APColor.nc,
            APMsg.skipping))

        return

    except APIRequestError as err:
        print("{}[ERROR]{} Error while processing AUR API response: {}{}".format(
            APColor.error, APColor.nc,
            str(err.reason),
            APMsg.skipping))

        return


    # filter out any non-R packages and VCS versions of R packages
    pkglist = [i for i in response_json["results"] if i["Name"].startswith("r-") and not i["Name"].endswith("-git")]

    if len(pkglist) == 0:
        print("{}[ERROR]{} There are no R packages for user {}{}{} in AUR{}".format(
            APColor.error, APColor.nc,
            APColor.data, username, APColor.nc,
            APMsg.skipping))

        return

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

        pool.apply_async(checker_worker, (pkglist[start_i:end_i], pkg_total, finished, output_info))

    # wait for all guys
    pool.close()
    pool.join()

    # print summary
    print("{}done{}".format(APColor.ok, APColor.nc))

    if len(output_info) == 0:
        print("{}[OK]{} All AUR R packages of user {}{}{} are up-to-date".format(
            APColor.ok, APColor.nc,
            APColor.data, username, APColor.nc))
    else:
        for line in output_info:
            print(line)


def main():
    """ main routine """

    # get command line options
    parser = argparse.ArgumentParser(description="Tool for easy management of AUR R packages")
    parser.add_argument("user", nargs='+', help="AUR username")
    parser.add_argument("--version", action="version", version="%(prog)s " + SCRIPT_VERSION)
    cmdline_args = vars(parser.parse_args())

    usernames = cmdline_args["user"]

    # perform updates checking for each user
    for username in usernames:
        print("{}[INFO]{} Checking R packages for user {}{}{}".format(
            APColor.info, APColor.nc,
            APColor.data, username, APColor.nc))

        check_user(username)

        print()

    # final print
    print("{}[OK]{} Job done".format(
        APColor.ok, APColor.nc))


## main program starts here
if __name__ == "__main__":
    main()


sys.exit(0)
