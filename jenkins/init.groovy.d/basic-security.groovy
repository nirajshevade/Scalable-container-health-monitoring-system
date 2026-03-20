// ============================================================
// Jenkins Initialisation Script
// Runs once at Jenkins startup to configure global settings.
// Placed in /usr/share/jenkins/ref/init.groovy.d/
// ============================================================
import jenkins.model.*
import hudson.security.*
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.*
import com.cloudbees.plugins.credentials.impl.*
import org.jenkinsci.plugins.plaincredentials.impl.*
import hudson.util.Secret
import java.util.logging.Logger

def logger = Logger.getLogger("init.groovy")
def jenkins = Jenkins.get()
def env = System.getenv()

// ─── Security Realm ─────────────────────────────────────────
def realm = new HudsonPrivateSecurityRealm(false)
def adminUser = env['JENKINS_ADMIN_USER'] ?: 'admin'
def adminPass = env['JENKINS_ADMIN_PASSWORD'] ?: 'Admin@Secure123'
realm.createAccount(adminUser, adminPass)
jenkins.setSecurityRealm(realm)

def strategy = new FullControlOnceLoggedInAuthorizationStrategy()
strategy.setAllowAnonymousRead(false)
jenkins.setAuthorizationStrategy(strategy)
logger.info("Security realm configured: user=${adminUser}")

// ─── Global Properties ──────────────────────────────────────
def globalProps = jenkins.getGlobalNodeProperties()
def envVarsNodePropertyClass = hudson.slaves.EnvironmentVariablesNodeProperty.class
if (!globalProps.getAll(envVarsNodePropertyClass)) {
    def envVarsNodeProperty = new hudson.slaves.EnvironmentVariablesNodeProperty()
    globalProps.add(envVarsNodeProperty)
    def envMap = envVarsNodeProperty.getEnvVars()
    envMap.put("DOCKER_REGISTRY", env['DOCKER_REGISTRY'] ?: "registry.example.com")
    envMap.put("IMAGE_NAME", env['IMAGE_NAME'] ?: "health-monitor")
    logger.info("Global environment variables configured")
}

// ─── Number of Executors ────────────────────────────────────
jenkins.setNumExecutors(4)
jenkins.setMode(Node.Mode.NORMAL)

// ─── Quieted Period ─────────────────────────────────────────
jenkins.setQuietPeriod(5)

// ─── Location Configuration ─────────────────────────────────
def jlc = JenkinsLocationConfiguration.get()
jlc.setUrl(env['JENKINS_URL'] ?: "http://localhost:8081/")
jlc.save()

jenkins.save()
logger.info("Jenkins initialisation complete")
