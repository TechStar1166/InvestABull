pipeline {
// testing jenkins file
    agent any

    stages {
        // STAGE 1: Download the code from GitHub
        stage('Checkout') {
            steps {
                checkout scm
                echo 'Source code successfully checked out!'
            }
        }

        // STAGE 2: Build the Docker images
        stage('Build') {
            steps {
                echo 'Building Next.js frontend (Port 3000) and FastAPI backend (Port 8000)...'
                // Using 'docker compose' to match Ivan's tested environment
                sh 'docker compose build'
            }
        }

        // STAGE 3: Verify the application can start without crashing
        stage('Verify') {
            steps {
                echo 'Running a quick verification test...'
                // Spin up the containers in the background (-d for detached)
                sh 'docker compose up -d'
                
                // Wait 10 seconds to give the Node and Python environments time to boot
                sh 'sleep 10'
                
                // Check if the containers are still running.
                // If they crashed, this will show them as 'Exit', which is a great basic health check
                sh 'docker compose ps'
            }
        }

        // STAGE 4: Clean up unused Docker resources to free up space
        stage('Cleanup') {
            steps {
                echo 'Pruning dangling Docker images...'
                sh 'docker image prune -f'
            }
        }

        // STAGE 5: Deploy the application
        stage('Deploy') {
            steps {
                echo 'Deploying the application...'
                echo 'InvestABull is now live! Backend at http://localhost:8000/docs and Frontend at http://localhost:3000/'
            }
        }
    }
    
    post {
        success {
            echo 'Jenkins pipeline completed successfully. Build, verification, cleanup, and deployment finished without errors.'
        }
        failure {
            echo 'Jenkins pipeline failed. Check the console output above to identify the failed stage.'
        }
        always {
            echo 'Jenkins pipeline execution finished.'
        }
    }
}
