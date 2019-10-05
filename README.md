# aurrpkgs
Make management of AUR R packages easy! Check for outdated R packages in AUR.

## Requirements
You should have working Python of version 3.2 (with SSL support) or newer installed on your system.

## How it works?
This tool makes request to the AUR API to get R packages (which names start with `r-`) of specific user. Then for every fetched R package it connects to the upstream repositories ([CRAN](https://cran.r-project.org/) or [Bioconductor](https://bioconductor.org/), for example) and requests for version info. This version string translates to [Arch-specific](https://wiki.archlinux.org/index.php/R_package_guidelines#Package_Version) way and script compares AUR version and upstream version. In case of outdated AUR package you will get notification.

If something went wrong you will see proper message - may be your `PKGBUILD` is somewhat broken or upstream URL is incorrect.

## Installation
This tool doesn't require any special installation procedure. Just clone the whole repo and you're ready!

### Arch Linux/Manjaro
To be always on the bleeding edge you can install this package from AUR with `yay` (or any other preferable AUR helper):
```
yay -S aurrpkgs-git
```

## Usage
Simply run:
```
./aurrpkgs.py user
```
or if you have installed version:
```
aurrpkgs user
```
where `user` is AUR username of interest.
