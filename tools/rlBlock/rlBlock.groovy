import org.apache.commons.io.*
import org.artifactory.common.*
import org.artifactory.fs.*
import org.artifactory.repo.*
import org.artifactory.repo.RepoPath
import org.artifactory.request.Request
import org.artifactory.resource.*
import org.artifactory.security.*

// If conditions are met, block download by returning 403

download {
    altResponse { Request request, RepoPath responseRepoPath ->
        try {
            log.info "download request ${responseRepoPath.toPath()} from: ${request.getClientAddress()}"

            String[] pathElements = responseRepoPath.toPath().split('/')
            String repoName = pathElements[0]

            final String PROPERTIES_FILE_PATH = 'plugins/rlBlock.properties'
            // Get some stuff from the properties file
            ConfigObject config = new ConfigSlurper().parse(
                new File(
                    ctx.artifactoryHome.etcDir,
                    PROPERTIES_FILE_PATH
                ).toURL()
            )

            String blockDownloadsFailed = config.block_downloads_failed ?: 'false'
            String[] noBlockFromIp = config.never_block_ip_list ?: []
            String[] neverBlockRepoList = config.never_block_repo_list ?: []

            if (
                blockDownloadsFailed.equalsIgnoreCase('true') &&
                !neverBlockRepoList.contains(repoName) &&
                !noBlockFromIp.contains(request.clientAddress)
            ) {
                String rlStatus = repositories.getProperties(responseRepoPath).getFirst('RL.scan-status')
                if (rlStatus && rlStatus.equalsIgnoreCase('fail')) {
                    msg = "Blocking download of ${responseRepoPath.toPath()} due to failed ReversingLabs assessment."
                    log.warn(msg)
                    message = msg
                    status = 403
                }
            }
        } catch (e) {
            log.error("Exception caught! Failed to execute plugin: ${e}")
            message = e.message
            status = 500
        }
    }
}
