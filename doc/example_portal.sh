#! /bin/bash
# ==================================================
# ==================================================
#  Parameters to adapt to your environment

# Virtual environment where we will install rl-scan-artifactory
export VENV="venv-rl-scan-artifactory"

# Temporary download location for artifacts
export DOWNLOAD_PATH="./download_temp" # a temp download location

# Requires python3 >= 3.10
export PYTHON_VERSION="python3.10"

# We write a log file in the directory where you start rl-scan-artifactory
export LOG_LEVEL="INFO" # one of [ERROR, WARNING, INFO, DEBUG]: default WARNING

# Artifactory: all 3 are required
export ARTIFACTORY_HOST="your artifactory host fqdn without https://"
export ARTIFACTORY_USER="your artifactory user configured to add properties"
export ARTIFACTORY_TOKEN="your artifactory token"

# Optional: set a proxy to reach Spectra Assure Portal and Artifactory
export PROXY_SERVER="" # your proxy server
export PROXY_PORT="" # if a host is specified, you also must set a port
export PROXY_USER="" # your proxy username
export PROXY_PASS="" # if a username is specified, you will most likely need to set a password

# If using Spectra Assure Portal: all 4 are required
export RLPORTAL_SERVER="Name of your Spectra Assure Portal instance"
export RLPORTAL_ORG="Spectra Assure Portal organization your account belongs to"
export RLPORTAL_GROUP="Spectra Assure Portal group your account is a member of"
export RLPORTAL_ACCESS_TOKEN="Personal access token for your Spectra Assure Portal account"

# Currently, only 'local' and 'remote' repositories are supported.
# Do not specify the cache repo name, but specify the remote repo name.
# The <remote name>-cache will be automatically used for scanning and setting properties.
REPOS_TO_SCAN=(
    rubygems-1 # remote repo, type gem
    maven2-dev # remote repo, type mvn
)

# You can also override all environment variables from an external file
[ -f ~/.env_testing ] && {
    source ~/.env_testing
}

# ==================================================
# ==================================================

make_venv()
{
    local what="pypi"

    VENV="venv-rl-scan-artifactory"
    PIP_INSTALL="pip3 -q --require-virtualenv --disable-pip-version-check --no-color install"

    "${PYTHON_VERSION}" -m venv "${VENV}"
    source "./${VENV}/bin/activate"

    case "${what}" in

    testpypi)
        ${PIP_INSTALL} \
            --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple \
            rl-scan-artifactory
        ;;

    pypi)
        ${PIP_INSTALL} rl-scan-artifactory
        ;;
    esac
}

scan_with_portal()
{
    # The --verbose option will show what item is being processed on stdout.
    # For Artifactory servers with a self-signed cert, use --ignore-cert-errors.
    # The --repo option supports a space-separated list of repository names from Artifactory,
    # or you can specify them one by one with --repo <one repo name>
    # To use Spectra Assure Portal for scanning, you need to specify -P or --portal.

    # Artifacts will be temporarily downloaded into this directory and automatically removed after scanning.
    # The specified download directory must already exist for the script get_files_artifactory.py to work.
    mkdir -p "${DOWNLOAD_PATH}"

    # --pack-safe will be silently ignored as it is irrelevant to the Portal

    rl-scan-artifactory \
        --verbose \
        --portal --sync --pack-safe \
        --ignore-cert-errors \
        --download "${DOWNLOAD_PATH}" \
        --repo ${REPOS_TO_SCAN[@]}
}

main()
{
    make_venv
    scan_with_portal
}

main "$@"
