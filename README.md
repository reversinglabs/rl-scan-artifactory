# rl-scan-artifactory

ReversingLabs provides the official Spectra Assure integration for [JFrog Artifactory](https://jfrog.com/artifactory/) to help software producers protect their organization, their development and build environments, and their customers by continuously monitoring and scanning software artifacts in Artifactory repositories.
**Only self-hosted Artifactory instances are supported**.

The integration is called `rl-scan-artifactory` and provided as a Python package that can be installed directly from PyPI.
The integration's GitHub repository also contains a separate Artifactory plugin called `rlBlock` which can be used to prevent access to specific artifacts based on their scanning results from `rl-scan-artifactory`.

The `rl-scan-artifactory` integration is most suitable for existing Spectra Assure users who want to protect their current or future Artifactory repositories in an automated, reliable way.

Depending on your use-case, the integration can rely on the Spectra Assure CLI (rl-secure or Docker image) or the Spectra Assure Portal when scanning artifacts.

It also allows for flexible workflows where you can scan some repositories with the Portal while scanning others with the CLI
(for example, if a repository contains artifacts you don't want to upload to the Portal).
Such combined workflows require an active license for both Spectra Assure products.

> **Note: This documentation assumes that you already have experience with JFrog Artifactory and with Python scripts.**


### What is Spectra Assure?

The [Spectra Assure platform](https://www.reversinglabs.com/products/software-supply-chain-security)
is a set of ReversingLabs products primarily designed for software assurance and software supply chain security use-cases.

It helps users protect their software supply chains by analyzing compiled software packages,
their components and third-party dependencies to detect exposures, reduce vulnerabilities, and eliminate threats before reaching production.

Users can choose to work with Spectra Assure as an on-premises [CLI tool](https://docs.secure.software/cli/),
a ReversingLabs-hosted [SaaS solution called Portal](https://docs.secure.software/portal/),
or use Spectra Assure [Docker images and integrations](https://docs.secure.software/integrations) in their CI/CD pipelines.


## How this integration works

This integration relies on [user-specified parameters](#parameters) to:

- check for [supported artifact types](#supported-artifactory-package-types) in the specified Artifactory repositories.
- scan the supported artifacts with the specified Spectra Assure product.
- save analysis reports to Artifactory and update artifact metadata with scan results and status information.


![SVG rl-scan-artifactory](doc/rl-scan-artifactory.drawio.svg)


The integration should be installed on a machine that can access and interact with a self-hosted JFrog Artifactory instance.
After it's installed, the integration can be started manually or scheduled to run in custom intervals.

When the integration is started for the first time, scanning may take many hours or even days depending on the size and the number of artifacts in the specified Artifactory repositories.

The integration downloads the artifacts to a temporary directory and scans them one by one using one of the selected Spectra Assure products.

The following products are supported:

- **Spectra Assure CLI (rl-secure)**. In this workflow, the integration scans artifacts locally without uploading them to ReversingLabs.
To scan the artifacts, `rl-secure` must be installed on the machine and a permanent package store must be initialized.
Analysis reports are automatically uploaded to Artifactory as a compressed file.
This workflow is ideal for users already familiar with the Spectra Assure CLI, and for those who need to scan their artifacts exclusively on-premises.

- **Spectra Assure CLI Docker image [reversinglabs/rl-scanner](https://hub.docker.com/r/reversinglabs/rl-scanner)**.
In this workflow, the integration scans artifacts locally inside the Docker container, without uploading them to ReversingLabs.
To scan the artifacts, the `rl-scanner` Docker image is used to run `rl-secure` in a container.
A package store must be initialized.
The `sync` option is not supported.
Analysis reports are automatically uploaded to Artifactory as a compressed file.
This workflow is ideal for users who want to scan their artifacts in ephemeral environments.

- **Spectra Assure Portal**. In this workflow, the integration uploads artifacts to a Portal instance for scanning.
The Portal account used for scanning must have valid credentials, and enough analysis capacity configured on the Portal.
The analysis report is accessible on the Portal and linked in the artifact metadata properties.
This workflow is ideal for users already familiar with the Spectra Assure Portal,
and for those who want a quick way to share analysis reports with internal and external stakeholders.

After the scan has finished, the integration applies [metadata properties](#artifactory-properties) on the scanned artifacts in Artifactory.

For each artifact, the properties indicate that it has been scanned with Spectra Assure and record its overall scan status (`pass` or `fail`).
This allows the integration to skip already scanned artifacts the next time it starts, and to scan only new artifacts in the repository.
It also allows users to prevent downloading artifacts that have the `fail` status with the [rlBlock Artifactory plugin](#blocking-artifact-downloads).


## Requirements and dependencies

- **A self-hosted Artifactory instance**. If you're not an experienced Artifactory user, we strongly recommend you [consult the official JFrog documentation](https://jfrog.com/help/r/jfrog-artifactory-documentation/jfrog-artifactory) for instructions.

- **An active, valid license for a Spectra Assure product.** You can use the Spectra Assure CLI, or the Spectra Assure Portal, or both products with this integration. For CLI workflows (with `rl-secure` or with the Docker image), we recommend getting the [site-wide deployment license](https://docs.secure.software/cli/licensing-guide). For Portal workflows, you need a [Personal Access Token](https://docs.secure.software/api/generate-api-token) for your Portal account.

- Python (minimal version: 3.10, tested with 3.10 - 3.13)

- [requests](https://pypi.org/project/requests/)

- [python-dateutil](https://pypi.org/project/python-dateutil/)

- [spectra-assure-sdk](https://pypi.org/project/spectra-assure-sdk/) >=1.0.3


### Supported Artifactory repository types

The following [repository types](https://jfrog.com/help/r/jfrog-artifactory-documentation/repository-management-overview) can be provided to the integration for scanning:

- **Local**
- **Remote**

Virtual repository types are currently not supported.

Cache repositories are implicitly used for all remote repository types.

### Writable repositories

In CLI workflows (with rl-secure or with the Docker image), analysis reports in user-specified formats are uploaded to Artifactory.

- For `local` repositories: the repository must be writable by the account executing the scan.
- For `remote` repositories: a custom, writable, local repository must be specified where the reports can be stored.

### Supported Artifactory package types

The following [package types](https://jfrog.com/help/r/jfrog-artifactory-documentation/supported-package-types) will be detected by the integration as supported artifacts for scanning:

- **Debian** - files ending in `.deb`
- **Docker** - `manifest.json` files. More details in the [Working with Docker images](#working-with-docker-images) section
- **RubyGems** - files ending in `.gem`
- **Generic** - files ending in `.rl_meta` when scanning with the Portal. When scanning with the CLI or CLI Docker image, all files are scanned and assigned a placeholder package URL, but it's not possible to use the `sync` option. More details in the [Working with generic repositories](#working-with-generic-repositories) section
- **Maven** - files ending in `.jar`
- **npm** - files ending in `.tgz`
- **PyPI** - files with properties `.name` and `.version`
- **RPM** - files ending in `.rpm`.


All files ending in `-reports.zip` are skipped regardless of the package type.

All files ending in `.rl_meta` are skipped.


## Installation

Before installing the integration, we recommend creating a virtual environment according to your preferences.

Install the latest version of the integration from PyPI with pip:

```
pip3 install rl-scan-artifactory
```

The installation makes the `rl-scan-artifactory` command available in your virtual environment.

You can then check the installed version with:

```
rl-scan-artifactory --version
```

Follow the [quick start guide](quick-start.md) for instructions on how to get started with the integration.


## Configuration

### Environment variables

All environment variables except `LOG_LEVEL` can also be passed to the `rl-scan-artifactory` command as parameters.
Their parameter names are listed in the **Equivalent parameter** column.


| Environment variable | Equivalent parameter | Description  |
| --                   | --                   | --           |
| ARTIFACTORY_HOST     | --artifactory-host   | **Required.** Fully qualified domain name (without `https://`) of your Artifactory server.  |
| ARTIFACTORY_USER     | --artifactory-user   | **Required.** Name of the Artifactory user configured to add properties. |
| ARTIFACTORY_TOKEN    | --artifactory-token  | **Required.** Access token for the specified Artifactory user. |
| PROXY_SERVER         | --proxy-server       | Server name for proxy configuration (IP address or DNS name). |
| PROXY_PORT           | --proxy-port         | Network port on the proxy server for proxy configuration. Required if PROXY_SERVER is used. |
| PROXY_USER           | --proxy-user         | User name for proxy authentication. |
| PROXY_PASS           | --proxy-pass         | Password for proxy authentication. Required if PROXY_USER is used. |
| LOG_LEVEL            | Not supported as parameter | Allows controlling the type of output messages displayed in the logs. Set to one of the following: `CRITICAL`, `WARNING`, `INFO`. Default is `WARNING` |


**CLI only**

| Environment variable | Equivalent parameter | Description  |
| --                   | --                   | --           |
| RLSECURE_SITE_KEY     | --rlsecure-site-key   | **Required only for the CLI Docker workflow.** The `rl-secure` license site key. The site key is a string generated by ReversingLabs and sent to users with the license file. |
| RLSECURE_ENCODED_LICENSE | --rlsecure-encoded-license | **Required only for the CLI Docker workflow.** The `rl-secure` license file as a Base64-encoded string. Users must encode the contents of their license file, and provide the resulting string with this variable.. |


**Portal only**

| Environment variable | Equivalent parameter | Description  |
| --                   | --                   | --           |
| RLPORTAL_SERVER       | --rlportal-server     | **Required only for the Portal workflow.** Name of the Portal instance to use for the scan. The Portal instance name usually matches the subdirectory of `my.secure.software` in your Portal URL. For example, if your Portal URL is `my.secure.software/demo`, the instance name to use with this parameter is `demo`. |
| RLPORTAL_GROUP        | --rlportal-group      | **Required only for the Portal workflow.** The name of a Portal group to use for the scan. The group must exist in the specified Portal organization. Group names are case-sensitive. |
| RLPORTAL_ORG          | --rlportal-org        | **Required only for the Portal workflow.** The name of a Portal organization to use for the scan. The organization must exist on the specified Portal instance. The user account authenticated with the token must be a member of the specified organization and have the appropriate permissions to upload and scan a file. Organization names are case-sensitive. |
| RLPORTAL_ACCESS_TOKEN | --rlportal-access-token | **Required only for the Portal workflow.**  A Personal Access Token for authenticating requests to the Portal. To use the Portal workflow with this integration, you must [create the token](https://docs.secure.software/api/generate-api-token) in your Portal settings. Tokens can expire and be revoked, in which case you'll have to update the value of this environment variable. It's strongly recommended to treat this token as a secret and manage it according to your organization's security best practices. |


### Parameters

One of the following parameters must always be specified to choose the Spectra Assure product that will be used for scanning: `--portal`, `--cli`, `--cli-docker`.

Depending on the product choice, some parameters may be ignored because they are incompatible with the specified product.

| Parameter |  Description  |
| --        | --            |
| --repo, -r    | **Required.** Specify one or more repository names to scan and monitor for artifacts. At least one repository name must be specified. To specify multiple repository names, separate them by space or comma, or repeat the parameter for each repository name. Specified repositories must have the [supported repository type](#supported-artifactory-repository-types) and contain artifacts that are among the [supported package types](#supported-artifactory-package-types). |
| --cli, -C    | Use the Spectra Assure CLI for artifact scanning and generating analysis reports. Requires `rl-deploy` or `rl-secure` to be installed. **Mutually exclusive with --portal and --cli-docker**. |
| --cli-docker | Use the Spectra Assure CLI Docker image (`reversinglabs/rl-scanner:latest`) for artifact scanning and generating analysis reports. Requires setting the environment variables `RLSECURE_ENCODED_LICENSE` and `RLSECURE_SITE_KEY`. **Mutually exclusive with --cli and --portal**. |
| --portal, -P    | Use the Spectra Assure Portal for artifact scanning and generating analysis reports. **Mutually exclusive with --cli and --cli-docker**.  |
| --cli-rlstore-path  | **Required when using --cli or --cli-docker**. Path to an existing [package store](https://docs.secure.software/cli/commands/init#package-store) that the integration can use. |
| --cli-rlsecure-path | **Required when using --cli**. Path to the locally installed `rl-secure` executable. |
| --sync, -S   | Enables reanalyzing previously scanned artifacts. If a package URL associated with an artifact already exists in the Portal or in the specified package store, this parameter instructs the integration to use the `sync` action instead of `scan`. **Not supported for --cli-docker**. <br />If using the rlBlock plugin, you won't be able to sync artifacts with status `fail` if you don't allow the server where `rl-scan-artifactory` is running from. Check the [plugin README](tools/rlBlock/README.md) for instructions. |
| --pack-safe | Include the [RL-SAFE archive](https://docs.secure.software/concepts/analysis-reports#rl-safe-archive) in the compressed file with analysis reports. **Incompatible with --portal** |
| --cli-reports-repo  | Compatibility parameter for storing reports in remote repositories. By default, Artifactory repositories of type `remote` cannot be used to store reports. The integration needs a custom `local` `generic` repository to store the reports (e.g `Spectra-Assure-Reports`), and it should be specified with this parameter. If not specified, all `remote` repositories will be skipped. |
| --download, -d   | Path to an existing directory that the integration can use for temporary artifact downloads from Artifactory. If not specified, Python `tempfile.gettempdir()` will be used. |
| --ignore-cert-errors | Allow working with invalid or self-signed certificates. Default: `false` |
| --ignore-artifactory-properties, -I | If specified, the integration will ignore any existing properties set for the scanned artifacts in Artifactory. |
| --verbose, -v    | Display more detailed progress messages and scan results on stdout. |
| --version, -V    | Show currently installed version of the integration and exit. |
| --cli-report-types | A comma-separated list of report formats to generate when using cli or cli-docker mode. <br />Supported values: `cyclonedx`, `rl-checks`, `rl-cve`, `rl-html`, `rl-json`, `rl-uri`, `sarif`, `spdx`, `all`. <br />Default: `all` |

### Artifactory properties

After scanning the artifacts, the integration adds metadata properties to each top-level item in the repository.
For Docker images, the properties are set on the `manifest.json` file.
The properties are also visible in the Artifactory GUI.

All properties have the `RL` prefix to indicate they are custom properties set by a ReversingLabs integration.

| Property            | Description     |
| --                  | --              |
| **RL.progress**     | Indicates the progress of the artifact scan. Can be one of the following values: 'upload_to_portal_ok', 'scanned'
| **RL.scan-status**  | Indicates the final status of the artifact scan. Can be one of the following values: 'pass', 'fail' |
| **RL.package-url**  | The [package URL](https://docs.secure.software/concepts/basic-concepts#package-url-purl) assigned to the artifact during upload to the Portal. The package URL is in the format `project/package@version`. You can use this information to identify and find the artifact in your Portal Projects. |
| **RL.scan-report**  | Direct URL to the analysis report for the scanned artifact. |
| **RL.group**        | Name of the Portal group associated with your account. Applies only if using the Portal. |
| **RL.organization** | Name of the Portal organization associated with your account. Applies only if using the Portal. |
| **RL.noscan**       | Used to skip scanning report files uploaded by the integration when using the CLI. Applies only if using the CLI or CLI Docker. Default value is 'true' |
| **RL.timestamp**    | UTC timestamp of the last operation performed on the artifact. Value: YYYY-MM-DDTHH:MM:SSZ |


## Working with Docker images

### Versioning
When Docker images are uploaded to Artifactory, they typically come with `manifest.json` files that describe each Docker image and its layers.
However, the file path to `manifest.json` may not have a version.
In that case, the integration will try to extract a version from the `config` or an associated `list.manifest.json`.

### Compatibility with rlBlock
In order for the `rlBlock` plugin to work properly,
Artifactory properties are set recursively on the directory containing the `manifest.json` file and all files under it.


### Marker files

Under certain circumstances (when a layer was already downloaded outside of Artifactory), a Docker image layer is represented by a marker file with zero (0) length.
This will make the Spectra Assure scan invalid.

To resolve this issue, you can use the [fix_marker.sh](tools/fix_marker.sh) script to properly populate all marker files.


## Working with generic repositories

Scanning repositories with the package type 'generic' requires a custom `.rl_meta` file for each artifact to allow creating proper package URLs.

- When scanning with `--portal`, only those artifacts with the `.rl_meta` file will be scanned.
- When scanning with `--cli` or `--cli-docker`, artifacts without the `.rl-meta` file will get a dummy package URL in the format `<repo name>/<filename>@v0`.

The custom `.rl_meta` file must be in `ini` format with a mandatory section called `rl_meta` like in the following example.

File name: `mypackagename-windows-arm_v8-1.0.99.rl_meta`

File contents:

```
[rl_meta]
namespace = windows
name = mypackagename
version = v1.0.99
architecture = arm_v8
path = mypackagename-windows-arm_v8-v1.0.99.msi
sha256 = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

The `rl_meta` section supports the following fields:

| Name          | Required | Description |
| --            | --        | -- |
| name          | Yes       | The name of the file identified by the `path` value. |
| version       | Yes       | The version of the file identified by the `path` value. |
| path          | Yes       | The relative path to the file (relative to the meta file). |
| namespace     | No        | Use if the name is not sufficiently unique on its own. |
| architecture  | No        | Should be used for binary packages (e.g. i386, amd64, arm_v8...). Can be set to 'none' for neutral source code, or can be left empty. |
| sha256        | No        | The SHA256 hash of the file identified by the `path` value. |

Optional fields can be empty.

The information from the `rl_meta` file is used to construct a unique package URL in the format `<project>/<package>@<version>` that will be used by the Spectra Assure Portal.
Specifically, the following components from the `rl_meta` file map to the parts of the package URL:

- project:  `<artifactory repository name>`
- package:  `[ <architecture>. ]` `[ <namespace>. ]` `<name>`
- version:  `<version>`

The resulting package URL should not contain `@` or `/` or any HTML-conflicting data.
If any of its parts do contain restricted substrings, they will be automatically converted to safe values so that a valid package URL can be constructed.

When using `--cli` or `--cli-docker` to scan a generic repository, the `rl_meta` file is not supported, and all files in the repository will be scanned.
In this case, a placeholder ("dummy") package URL is used for both `--cli` and `--cli-docker`.
Because generic items without a proper package URL cannot be reanalyzed, the `sync` option is not supported.


## Blocking artifact downloads

Optionally, an Artifactory plugin called `rlBlock` can be used together with the `rl-scan-artifactory` integration to prevent download requests for artifacts that received the `fail` status after analysis.

Download blocking must be enabled in the plugin's `.properties` file.
If enabled, the plugin checks the artifact properties whenever a download request is received by Artifactory.
If a Spectra Assure scan status property exists for an artifact and its value is "fail", the plugin immediately returns HTTP 403 and a JSON body with a message stating that the download was blocked due to a failing ReversingLabs Spectra Assure scan.
If the property doesn't exist for an artifact or its value is "pass", the plugin allows the download to continue as normal.

To use the plugin, download it directly from the `rl-scan-artifactory` GitHub repository.
Find more detailed configuration instructions in the [plugin README](tools/rlBlock/README.md).


## Useful resources

- [Official JFrog Artifactory documentation](https://jfrog.com/help/r/jfrog-artifactory-documentation/jfrog-artifactory)
- [Analysis report formats](https://docs.secure.software/concepts/analysis-reports) supported by Spectra Assure products
- [Communities, programming languages](https://docs.secure.software/concepts/language-coverage) and [file formats](https://docs.secure.software/concepts/filetypes) supported by Spectra Assure products
