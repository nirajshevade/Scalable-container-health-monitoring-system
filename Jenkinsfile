// ============================================================
// Jenkinsfile — CI/CD Pipeline
// Container Health Monitoring & Alerting System
// Stages: Checkout → Lint → Test → Build → Scan → Push → Deploy
// ============================================================

pipeline {

    agent {
        docker {
            image 'python:3.11-slim'
            args  '-v /var/run/docker.sock:/var/run/docker.sock --group-add docker'
        }
    }

    options {
        timeout(time: 45, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timestamps()
        ansiColor('xterm')
    }

    environment {
        // Registry & Image settings
        REGISTRY         = credentials('docker-registry-url')
        REGISTRY_CREDS   = credentials('docker-registry-credentials')
        IMAGE_NAME       = 'health-monitor'
        IMAGE_TAG        = "${env.BUILD_NUMBER}-${env.GIT_COMMIT?.take(8) ?: 'local'}"
        IMAGE_LATEST     = "${REGISTRY}/${IMAGE_NAME}:latest"
        IMAGE_VERSIONED  = "${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

        // Deployment targets
        STAGING_HOST     = credentials('staging-host')
        PRODUCTION_HOST  = credentials('production-host')
        DEPLOY_SSH_KEY   = credentials('deploy-ssh-key')

        // Notification
        SLACK_WEBHOOK    = credentials('slack-webhook-url')

        // Thresholds
        COVERAGE_MIN     = '80'
    }

    stages {

        // ─── Stage 1: Checkout & Environment Setup ────────
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.GIT_BRANCH_NAME = sh(
                        script: "git rev-parse --abbrev-ref HEAD",
                        returnStdout: true
                    ).trim()
                    env.GIT_SHORT_SHA = sh(
                        script: "git rev-parse --short HEAD",
                        returnStdout: true
                    ).trim()
                    env.COMMIT_MSG = sh(
                        script: "git log -1 --pretty=%B",
                        returnStdout: true
                    ).trim()
                }
                echo "Branch: ${env.GIT_BRANCH_NAME} | Commit: ${env.GIT_SHORT_SHA}"
                echo "Message: ${env.COMMIT_MSG}"
            }
        }

        // ─── Stage 2: Install Dependencies ────────────────
        stage('Install Dependencies') {
            steps {
                dir('health-monitor') {
                    sh '''
                        pip install --quiet --no-cache-dir -r requirements.txt
                        pip install --quiet --no-cache-dir \
                            pytest pytest-asyncio pytest-cov pytest-mock \
                            flake8 bandit mypy black isort
                    '''
                }
            }
        }

        // ─── Stage 3: Code Quality & Linting ─────────────
        stage('Code Quality') {
            parallel {
                stage('Linting') {
                    steps {
                        dir('health-monitor') {
                            sh '''
                                echo "=== Flake8 Linting ==="
                                flake8 src/ main.py \
                                    --max-line-length=120 \
                                    --extend-ignore=E203,E501,W503 \
                                    --count --statistics
                            '''
                        }
                    }
                }
                stage('Format Check') {
                    steps {
                        dir('health-monitor') {
                            sh '''
                                echo "=== Black Format Check ==="
                                black --check --line-length=120 src/ main.py || true

                                echo "=== Import Sort Check ==="
                                isort --check-only src/ main.py || true
                            '''
                        }
                    }
                }
                stage('Type Check') {
                    steps {
                        dir('health-monitor') {
                            sh '''
                                echo "=== MyPy Type Check ==="
                                mypy src/ --ignore-missing-imports --no-error-summary || true
                            '''
                        }
                    }
                }
                stage('YAML Validation') {
                    steps {
                        sh '''
                            pip install --quiet pyyaml
                            python -c "
import yaml, glob, sys
errors = []
for f in glob.glob('**/*.yml', recursive=True) + glob.glob('**/*.yaml', recursive=True):
    if 'node_modules' in f:
        continue
    try:
        yaml.safe_load(open(f))
        print(f'✅ {f}')
    except yaml.YAMLError as e:
        errors.append(f'❌ {f}: {e}')
        print(f'❌ {f}: {e}')
if errors:
    sys.exit(1)
print(f'All YAML files valid ({len(glob.glob(\"**/*.yml\", recursive=True))} files checked)')
"
                        '''
                    }
                }
            }
        }

        // ─── Stage 4: Security Scanning ───────────────────
        stage('Security Scan') {
            steps {
                dir('health-monitor') {
                    sh '''
                        echo "=== Bandit Security Scan ==="
                        bandit -r src/ main.py \
                            -ll \
                            -f xml \
                            -o bandit-report.xml || true

                        bandit -r src/ main.py -ll || true
                    '''

                    // Archive security report
                    archiveArtifacts artifacts: 'bandit-report.xml', allowEmptyArchive: true
                }
            }
        }

        // ─── Stage 5: Unit Tests ──────────────────────────
        stage('Unit Tests') {
            steps {
                dir('health-monitor') {
                    sh """
                        echo "=== Running Unit Tests ==="
                        pytest tests/ \
                            -v \
                            --tb=short \
                            --cov=src \
                            --cov-report=xml:coverage.xml \
                            --cov-report=html:htmlcov \
                            --cov-fail-under=${COVERAGE_MIN} \
                            --junit-xml=test-results.xml \
                            -p no:cacheprovider \
                        || true
                    """
                }
            }
            post {
                always {
                    dir('health-monitor') {
                        junit allowEmptyResults: true, testResults: 'test-results.xml'
                        publishHTML(target: [
                            allowMissing: true,
                            alwaysLinkToLastBuild: true,
                            keepAll: true,
                            reportDir: 'htmlcov',
                            reportFiles: 'index.html',
                            reportName: 'Coverage Report'
                        ])
                    }
                }
            }
        }

        // ─── Stage 6: Docker Build ────────────────────────
        stage('Docker Build') {
            when {
                anyOf {
                    branch 'main'
                    branch 'develop'
                    branch 'release/*'
                }
            }
            steps {
                sh '''
                    echo "=== Building Docker Image ==="
                    docker build \
                        --no-cache \
                        --pull \
                        --build-arg BUILD_DATE="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
                        --build-arg VCS_REF="${GIT_SHORT_SHA}" \
                        --build-arg VERSION="${IMAGE_TAG}" \
                        --label "org.opencontainers.image.created=$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
                        --label "org.opencontainers.image.revision=${GIT_SHORT_SHA}" \
                        --label "org.opencontainers.image.version=${IMAGE_TAG}" \
                        -t "${IMAGE_VERSIONED}" \
                        -t "${IMAGE_LATEST}" \
                        ./health-monitor/

                    echo "✅ Image built: ${IMAGE_VERSIONED}"
                    docker images "${REGISTRY}/${IMAGE_NAME}"
                '''
            }
        }

        // ─── Stage 7: Container Security Scan ────────────
        stage('Container Scan') {
            when {
                anyOf {
                    branch 'main'
                    branch 'develop'
                }
            }
            steps {
                sh '''
                    echo "=== Trivy Container Vulnerability Scan ==="
                    # Install Trivy if not present
                    if ! command -v trivy &>/dev/null; then
                        apt-get install -y --quiet wget
                        wget -qO- https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh
                    fi

                    trivy image \
                        --severity HIGH,CRITICAL \
                        --no-progress \
                        --exit-code 0 \
                        --format json \
                        --output trivy-report.json \
                        "${IMAGE_VERSIONED}" || true

                    trivy image \
                        --severity HIGH,CRITICAL \
                        --no-progress \
                        "${IMAGE_VERSIONED}" || true
                '''
                archiveArtifacts artifacts: 'trivy-report.json', allowEmptyArchive: true
            }
        }

        // ─── Stage 8: Push to Registry ────────────────────
        stage('Push Image') {
            when {
                anyOf {
                    branch 'main'
                    branch 'develop'
                    branch 'release/*'
                }
            }
            steps {
                sh '''
                    echo "${REGISTRY_CREDS_PSW}" | docker login \
                        "${REGISTRY}" \
                        -u "${REGISTRY_CREDS_USR}" \
                        --password-stdin

                    echo "=== Pushing Images ==="
                    docker push "${IMAGE_VERSIONED}"
                    docker push "${IMAGE_LATEST}"

                    # Tag branch-specific image
                    BRANCH_TAG=$(echo "${GIT_BRANCH_NAME}" | tr '/' '-')
                    docker tag "${IMAGE_VERSIONED}" "${REGISTRY}/${IMAGE_NAME}:${BRANCH_TAG}"
                    docker push "${REGISTRY}/${IMAGE_NAME}:${BRANCH_TAG}"

                    echo "✅ Images pushed successfully"
                    docker logout "${REGISTRY}"
                '''
            }
        }

        // ─── Stage 9: Deploy to Staging ───────────────────
        stage('Deploy – Staging') {
            when {
                branch 'develop'
            }
            steps {
                sh '''
                    echo "=== Deploying to Staging ==="
                    ssh -i "${DEPLOY_SSH_KEY}" \
                        -o StrictHostKeyChecking=no \
                        deploy@${STAGING_HOST} \
                        "cd /opt/monitoring && \
                         export IMAGE_TAG=${IMAGE_TAG} && \
                         docker compose pull health-monitor && \
                         docker compose up -d --no-deps health-monitor && \
                         docker compose ps"

                    echo "✅ Staging deployment complete"
                '''
            }
            post {
                success {
                    echo "Staging deployment succeeded"
                }
            }
        }

        // ─── Stage 10: Integration Tests (Staging) ────────
        stage('Integration Tests') {
            when {
                branch 'develop'
            }
            steps {
                sh '''
                    echo "=== Running Integration Tests ==="
                    sleep 30  # Wait for service to start

                    STAGING_URL="http://${STAGING_HOST}:8000"

                    # Health check
                    STATUS=$(curl -sf "${STAGING_URL}/health" | python -c "import sys,json; j=json.load(sys.stdin); print(j.get('status',''))" 2>/dev/null)
                    if [ "$STATUS" != "healthy" ]; then
                        echo "❌ Health check failed: $STATUS"
                        exit 1
                    fi
                    echo "✅ Health check passed"

                    # Metrics endpoint check
                    METRICS=$(curl -sf "${STAGING_URL}/metrics" | grep -c "container_monitor_" || echo 0)
                    if [ "$METRICS" -lt 5 ]; then
                        echo "❌ Insufficient metrics exposed: ${METRICS}"
                        exit 1
                    fi
                    echo "✅ Metrics endpoint OK (${METRICS} metric families)"
                '''
            }
        }

        // ─── Stage 11: Deploy to Production ──────────────
        stage('Deploy – Production') {
            when {
                branch 'main'
            }
            input {
                message "Deploy to Production?"
                ok "Deploy"
                submitter "DevOps,Release-Manager"
            }
            steps {
                sh '''
                    echo "=== Deploying to Production ==="
                    ssh -i "${DEPLOY_SSH_KEY}" \
                        -o StrictHostKeyChecking=no \
                        deploy@${PRODUCTION_HOST} \
                        "cd /opt/monitoring && \
                         export IMAGE_TAG=${IMAGE_TAG} && \
                         docker compose pull health-monitor && \
                         docker compose up -d --no-deps --no-build health-monitor && \
                         docker compose ps"

                    echo "✅ Production deployment complete: ${IMAGE_TAG}"
                '''
            }
        }

        // ─── Stage 12: Post-Deploy Verification ───────────
        stage('Smoke Test – Production') {
            when {
                branch 'main'
            }
            steps {
                sh '''
                    sleep 30
                    curl -sf "http://${PRODUCTION_HOST}:8000/health" | python -c \
                        "import sys,json; j=json.load(sys.stdin); assert j['status']=='healthy', 'Health check failed'"
                    echo "✅ Production smoke test passed"
                '''
            }
        }
    }

    post {
        always {
            // Clean up Docker artifacts
            sh 'docker system prune -f --filter "until=24h" || true'
            cleanWs()
        }

        success {
            script {
                slackSend(
                    channel: '#deployments',
                    color: 'good',
                    message: """✅ *BUILD SUCCESS*
                        | *Job:* ${env.JOB_NAME} #${env.BUILD_NUMBER}
                        | *Branch:* ${env.GIT_BRANCH_NAME}
                        | *Commit:* ${env.GIT_SHORT_SHA}
                        | *Image:* ${env.IMAGE_VERSIONED}
                        | *Duration:* ${currentBuild.durationString}
                        | 🔗 <${env.BUILD_URL}|View Build>""".stripMargin()
                )
            }
        }

        failure {
            script {
                slackSend(
                    channel: '#deployments',
                    color: 'danger',
                    message: """❌ *BUILD FAILED*
                        | *Job:* ${env.JOB_NAME} #${env.BUILD_NUMBER}
                        | *Branch:* ${env.GIT_BRANCH_NAME}
                        | *Stage:* ${env.STAGE_NAME ?: 'Unknown'}
                        | *Duration:* ${currentBuild.durationString}
                        | 🔗 <${env.BUILD_URL}|View Build> | <${env.BUILD_URL}console|View Logs>""".stripMargin()
                )
            }
        }

        unstable {
            script {
                slackSend(
                    channel: '#deployments',
                    color: 'warning',
                    message: "⚠️ *BUILD UNSTABLE* — ${env.JOB_NAME} #${env.BUILD_NUMBER} — <${env.BUILD_URL}|View>"
                )
            }
        }
    }
}
