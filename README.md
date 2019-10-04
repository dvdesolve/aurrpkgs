# aurrpkgs
Make management of AUR R packages easy! Check for outdated R packages in AUR.

## Requirements
You should have working Python of version 3.2 or newer installed on your system.

## Installation
This tool doesn't require any special installation procedure. Just clone the whole repo and you're ready!

### Arch Linux/Manjaro
To be always on the bleeding edge you can install this package from AUR with `yay` (or any preferable AUR helper):
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

## Limitations
As for now `aurrpkgs` doesn't support repositories other than CRAN. This will be fixed soon.
