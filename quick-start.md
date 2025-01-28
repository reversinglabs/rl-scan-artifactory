# Get started with rl-scan-artifactory

In this guide, you will learn how to scan artifacts in your Artifactory repository with all supported Spectra Assure products:

- the [CLI](#CLI)
- the [Portal](#Portal)
- the [CLI Docker image](#Docker)

The guide relies on example scripts provided in this GitHub repository.
You can copy the scripts and modify them to include the configuration relevant for your use-case.


## Prerequisites

The following tasks should be completed before you start working with the integration:

- **Get the credentials for your Artifactory account**. The integration requires the user name and token to authenticate to your Artifactory server.


## Configuration

For the purposes of this guide, all example scripts use the same Artifactory server and a virtual environment to install `rl-scan-artifactory`.
We're going to explicitly configure the Python version.

In the configuration, we're also specifying some optional parameters:

- the download path for the temporary storage of all artifacts that will be scanned
- the log level

```shell

# Virtual environment where we will install rl-scan-artifactory
export VENV="venv-rl-scan-artifactory"

# Temporary download location for artifacts
export DOWNLOAD_PATH="./download_temp"

# Requires python3 >= 3.10
export PYTHON_VERSION="python3.10"

# We write a log file in the directory where you start rl-scan-artifactory
export LOG_LEVEL="WARNING" # one of [ERROR, WARNING, INFO]: default WARNING

# Artifactory: all 3 are mandatory
export ARTIFACTORY_HOST="your artifactory host fqdn without https://"
export ARTIFACTORY_USER="your artifactory user configured to add properties"
export ARTIFACTORY_TOKEN="your artifactory token"

# Optional: set a proxy to reach Spectra Assure Portal and Artifactory
export PROXY_SERVER="" # your proxy server
export PROXY_PORT="" # if a host is specified, you also must set a port
export PROXY_USER="" # optional
export PROXY_PASS="" # if a user is specified, you will most likely need a password

# We only support 'local' and 'remote' repositories.
# Do not specify the cache repo name but specify the remote repo name.
# We will automatically use the <remote name>-cache for scanning and setting properties.
REPOS_TO_SCAN=(
    rubygems-1 # remote repo, type gem
    maven2-dev # remote repo, type mvn
)
```

## CLI

To use the Spectra Assure CLI (`rl-secure`) for scanning artifacts, you will have to specify the location of CLI executables (`rl-secure` and `rl-safe`) on the system where you are running the integration.
This means that the CLI must be installed on your system before you can use the integration.
You can install `rl-secure` locally with the [rl-deploy tool](https://docs.secure.software/cli/deployment/rl-deploy-quick-start).

You will also have to provide the path to an existing package store, or [create one](https://docs.secure.software/cli/commands/init) if you don't have it yet.

```shell
# When using rl-secure, we need a previously initialized package store:
export RL_STORE_PATH="$HOME/tmp/rl-secure/"

# The directory where we can find the rl-secure executable:
export RL_SECURE_PATH="$HOME/tmp/rl-secure/"
```

If you want to scan `remote` Artifactory repositories, you will have to specify a location where the integration can store analysis reports.
Because `remote` and `cache` repository types can't be used to upload new information, a `local` repository type must be used for the reports.

If you don't provide the name of a `local` Artifactory repository to store reports, all `remote` repositories from your configuration will be ignored.

```shell
# If using Spectra Assure CLI with rl-secure or Docker as a backend
# and scanning Artifactory 'remote' repositories,
# you need to create a holding repo for the scan reports of type 'local generic'.
# The 'local generic' repo must be manually created first by your admin.
RL_REPORTS_REPO="Spectra-Assure-Reports"
```

**Complete the configuration in the example script and run it:** [example_cli.sh](./doc/example_cli.sh)


## Portal

To use the Spectra Assure Portal for scanning artifacts, you will have to specify the following details in the configuration:

```shell
# Spectra Assure Portal: all 4 are mandatory
export RLPORTAL_SERVER="Name of your Spectra Assure Portal instance"
export RLPORTAL_ORG="Spectra Assure Portal organization your account belongs to"
export RLPORTAL_GROUP="Spectra Assure Portal group your account is a member of"
export RLPORTAL_ACCESS_TOKEN="Personal access token for your Spectra Assure Portal account"
```

**Complete the configuration in the example script and run it:** [example_portal.sh](./doc/example_portal.sh)


## Docker

To use the Spectra Assure CLI Docker image (`reversinglabs/rl-scanner:latest`) for scanning artifacts, you will have to specify the site key and the Base64-encoded license file of your [site-wide deployment license](https://docs.secure.software/cli/licensing-guide#site-wide-deployment-license).

If you don't provide the path to an external package store, an ephemeral store is created inside the Docker container.

```shell
# Required
export RLSECURE_SITE_KEY='< your site key>'
export RLSECURE_ENCODED_LICENSE='<your encoded license>'

# Optional: When using Docker with a external package store, it needs to be previously initialized
# If there is no external store (which is fine),
# there will be no history collected as the store inside the Docker container is ephemeral.
export RL_STORE_PATH="$HOME/tmp/rl-secure/"
```

If you want to scan `remote` Artifactory repositories, you will have to specify a location where the integration can store analysis reports.
Because `remote` and `cache` repository types can't be used to upload new information, a `local` repository type must be used for the reports.

If you don't provide the name of a `local` Artifactory repository to store reports, all `remote` repositories from your configuration will be ignored.

```shell
# If using Spectra Assure CLI with rl-secure or Docker as a backend
# and scanning Artifactory 'remote' repositories,
# you need to create a holding repo for the scan reports of type 'local generic'.
# The 'local generic' repo must be manually created first by your admin.
RL_REPORTS_REPO="Spectra-Assure-Reports"
```

**Complete the configuration in the example script and run it:** [example_docker.sh](./doc/example_docker.sh)
