#! /bin/bash

make clean


find . -type f -print | grep -v './.git/' | xargs sha256sum
