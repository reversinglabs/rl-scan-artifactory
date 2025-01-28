#! /bin/bash

# intermediate files
TEMP_LAYERS="marker_layers-$$.txt"
TEMP_PATHS="marker_paths-$$.txt"
TEMP_MARKERS="download_markers-$$.txt"

ask_questions_prep()
{
    echo "Resolve Docker files ending with .marker (size 0) into real files so that we can download them."
    echo

    echo -n "Enter your Artifactory URL: (including the /artifactory part. e.g: 'https://fqdn-hostname/artifactory/'): "
    read ARTIFACTORY_HOST_URL

    echo -n "Enter your Docker remote repository name without the '-cache' suffix: "
    read ARTIFACTORY_DOCKER_REPO_NAME

    echo -n "Enter username with Read and Deploy permissions to the specified repository in Artifactory: "
    read ARTIFACTORY_USERNAME

    echo -n "Password for Artifactory: "
    read -s ARTIFACTORY_PASSWORD

    ARTIFACTORY_SOURCE_URL="${ARTIFACTORY_HOST_URL%/}" # remove any trailing '/'
    DOCKER_CACHE_REPO_NAME="${ARTIFACTORY_DOCKER_REPO_NAME}-cache"
    AQL_URL="${ARTIFACTORY_SOURCE_URL}/api/search/aql"
    DOCKER_URL="${ARTIFACTORY_SOURCE_URL}/api/docker"
}

get_status()
{
    local status_code=$(
        curl \
            -X POST \
            -sS \
            -u"${ARTIFACTORY_USERNAME}:${ARTIFACTORY_PASSWORD}" \
            --write-out '%{http_code}' \
            --silent \
            --output /dev/null \
            "${AQL_URL}" \
            -d 'items.find({"$and": [{"repo" : "'"${DOCKER_CACHE_REPO_NAME}"'"}, {"name" : {"$match" : "*.marker"}}]})' \
            -H "Content-Type: text/plain"
    )

    local general="Request failed with HTTP '$status_code'.\nPlease check the Artifactory URL and Remote Repository, and make sure they are correct."

    [ "${status_code}" != "200" ] && {
        echo

        case "${status_code}" in
        000)
            echo "Request failed with Could not resolve host: '${AQL_URL}'.\nPlease check the Artifactory URL and make sure it is correct"
            ;;
        401)
            echo "Request failed with HTTP '$status_code'.\nPlease check the provided username and password for Artifactory"
            ;;
        *)
            echo "${general}"
            ;;
        esac
        exit 101
    }
}

get_markers_info()
{
    curl \
        -X POST \
        -sS \
        -u"${ARTIFACTORY_USERNAME}:${ARTIFACTORY_PASSWORD}" \
        "${AQL_URL}" \
        -d 'items.find({"$and": [{"repo" : "'"${DOCKER_CACHE_REPO_NAME}"'"}, {"name" : {"$match" : "*.marker"}}]})' \
        -H "Content-Type: text/plain" \
        > "${TEMP_LAYERS}"

    jq -M -r '.results[] | "\(.path)/blobs/\(.name)"' "${TEMP_LAYERS}" > "${TEMP_PATHS}"

    sed 's/[“,]//g' "${TEMP_PATHS}" |
    sed 's|library/||g' |
    sed 's/.marker//g' |
    sed "s/__/:/g" |
    awk 'sub("[/][^,;/]+[/]blobs/", "/blobs/", $0)' > "${TEMP_MARKERS}"

    echo
    echo
    echo -n "The current number of marker layers in this repository is: "
    cat "${TEMP_MARKERS}" |
    wc -l
    echo
    cat "${TEMP_MARKERS}"
}

download_all_layers_in_file()
{
    while read p
    do
        local prefix="${DOCKER_URL}/${ARTIFACTORY_DOCKER_REPO_NAME}/v2/$p"
        echo -n "${p}: "
        curl \
            -sS \
            -u"${ARTIFACTORY_USERNAME}:${ARTIFACTORY_PASSWORD}" \
            -w "HTTP/1.1 %{http_code} | %{time_total} seconds | %{size_download} bytes\\n" \
            "${prefix}" \
            -o /dev/null # no background tasks, we can wait nicely
    done <"${TEMP_MARKERS}"
}

cleanup()
{
    rm -f "${TEMP_LAYERS}" "${TEMP_PATHS}" "${TEMP_MARKERS}"
}

do_download_or_not()
{
    echo
    echo -n "Do you want to download these marker layers? (yes/no), default: no. : "
    read input

    # make lowercase
    local input=$(
        echo "${input}" |
        sed "y/ABCDEFGHIJKLMNOPQRSTUVWXYZ/abcdefghijklmnopqrstuvwxyz/"
    )

    [ "${input}" != "yes" ] && { # we only accept the lowercase 'yes' as a valid answer!
        echo "Skipping the download of marker layers"
        return
    }

    download_all_layers_in_file
}

validate_tempfiles_dont_exist()
{
    for i in "${TEMP_LAYERS}" "${TEMP_PATHS}" "${TEMP_MARKERS}"
    do
        [ -z "${i}" ] && {
            cat <<!
The temp file '${i}' we will use already exists.
As the file would be overwritten, we will not run the script here.
Please use a different location to run this script,
e.g. create a ./tmp directory and run it there.
!
            exit 101
        }
    done
}

main()
{
    ask_questions_prep
    get_status
    get_markers_info
    do_download_or_not
    cleanup
}

main
