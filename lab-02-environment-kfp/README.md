# Setting up an MLOps environment on GCP.

The labs in this repo are designed to run in a reference MLOps environment. The environment is configured to support effective development and operationalization of production grade ML workflows.

![Reference topolgy](/images/lab_300.png)

The core services in the environment are:
- AI Platform Notebooks - ML experimentation and development
- AI Platform Training - scalable, serverless model training
- AI Platform Prediction - scalable, serverless model serving
- Dataflow - distributed data processing
- BigQuery - analytics data warehouse
- Cloud Storage - unified object storage
- TensorFlow Extended/Kubeflow Pipelines (TFX/KFP) - machine learning pipelines
- Cloud SQL - machine learning metadata  management
- Cloud Build - CI/CD
    

In this lab, you will provision a lightweight deployment of **Kubeflow Pipelines**. 

Since other services are configured in the `lab-01-environment-notebook` lab you need to complete that lab before proceeding.



## Deploying Kubeflow Pipelines 

The below diagram shows an MVP environment for a lightweight deployment of Kubeflow Pipelines on GCP:

![KFP Deployment](/images/kfp.png)

The environment includes:
- A VPC to host GKE cluster
- A GKE cluster to host KFP services
- A Cloud SQL managed MySQL instance to host KFP and ML Metadata databases
- A Cloud Storage bucket to host artifact repository

The KFP services are deployed to the GKE cluster and configured to use the Cloud SQL managed MySQL instance. The KFP services access the Cloud SQL through [Cloud SQL Proxy](https://cloud.google.com/sql/docs/mysql/sql-proxy). External clients use [Inverting Proxy](https://github.com/google/inverting-proxy) to interact with the KFP services.


*The current versions of the labs have been tested with Kubeflow Pipelines v1.36. KFP v1.37, v1.38, v1.39 introduced [the issue](https://github.com/kubeflow/pipelines/issues/2764) that causes some labs to fail. After the issue is addressed we will update the setup to utilize the newer version of KFP.*

Provisioning of the environment has been broken into two steps. In the first step you provision and configure core infrastructure services required to host **Kubeflow Pipelines**, including GKE, Cloud SQL and Cloud Storage. In the second step you deploy and configure **Kubeflow Pipelines**.

The provisioning of the infrastructure components  has been automated with Terraform  The Terraform HCL configurations can be found in the `kfp/terraform` folder. The deployment of **Kubeflow Pipelines** is facilitated with [Kustomize](https://kustomize.io/). The Kustomize overlays are in the `kfp/kustomize` folder.

Both **Terraform** and **Kustomize** are part of the custom container image used by your **AI Platform Notebook** instance.



### Deploying infrastructure services to host Kubeflow Pipelines

1. Connect to **JupyterLab** on the **AI Platform Notebooks** instance created in the `lab-01-environment-notebook` lab.

2. Open the **JupyterLab** terminal

3. Clone this repo under the `home` folder.
```
cd /home
git clone https://github.com/jarokaz/mlops-labs.git
cd mlops-labs/lab-02-environment-kfp
```

4. Provision infrastructure:
```
./provision-infra.sh [PROJECT_ID] [REGION] [ZONE] [PREFIX]
```
Where 
- `[PROJECT_ID]` - your project ID
- `[REGION]` - the region for a Cloud SQL instance. We recommend using `us-central1`
- `[ZONE]` - the zone for a GKE cluster. We recommend using `us-central1-a`
- `[PREFIX]` - the name prefix that will be added to the names of provisioned resources
4. Review the logs generated by the script for any errors.

### Installing Kubeflow Pipelines components
```
./deploy-kfp.sh  [PROJECT_ID] [NAMESPACE] [SQL_PASSWORD]
```
Where:
- `[PROJECT_ID]` - your project ID
- `[NAMESPACE]` - the namespace to host KFP components
- `[SQL_PASSWORD]` - the password for the Cloud SQL `root` user

*Note: The `deploy-kfp.sh` script does not allow you to specify a SQL username. The reason is that in the current versions of KFP the SQL username must be `root`*.

## Accessing KFP UI

After the installation completes, you can access the KFP UI from the following URL. You may need to wait a few minutes before the URL is operational.

```
echo "https://"$(kubectl describe configmap inverse-proxy-config -n [NAMESPACE] | grep "googleusercontent.com")
```