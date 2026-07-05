// ============================================================
// Jenkins Plugin Installation Script
// Ensures required plugins are installed and up to date.
// ============================================================
import jenkins.model.*
import java.util.logging.Logger

def logger = Logger.getLogger("install-plugins.groovy")
def jenkins   = Jenkins.get()
def pluginMgr = jenkins.getPluginManager()
def updateCtr = jenkins.getUpdateCenter()

def requiredPlugins = [
    "git",
    "workflow-aggregator",          // Pipeline
    "pipeline-stage-view",
    "blueocean",
    "docker-workflow",
    "docker-plugin",
    "credentials-binding",
    "environment-injector",
    "junit",
    "cobertura",
    "slack",
    "email-ext",
    "timestamper",
    "ansicolor",
    "ws-cleanup",
]

try {
    updateCtr.updateAllSites()

    def pluginsToInstall = requiredPlugins.findAll { pluginId ->
        !pluginMgr.getPlugin(pluginId)
    }

    if (pluginsToInstall) {
        logger.info("Installing plugins: ${pluginsToInstall}")
        def installFutures = pluginsToInstall.collect { pluginId ->
            updateCtr.getPlugin(pluginId)?.deploy(true)
        }.findAll { it != null }
        installFutures*.get()
        jenkins.restart()
    } else {
        logger.info("All required plugins already installed")
    }
} catch (Throwable e) {
    logger.warning("Failed to install or update plugins during startup due to network error: " + e.message)
    logger.warning("Jenkins will continue to boot, but you may need to install plugins manually via the UI.")
}
