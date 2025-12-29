# **Standard Operating Procedure: Databricks Asset Bundles (DABs) Deployment**

**Document Owner:** Gambill Data Engineering

**Scope:** All Data Engineering Pipelines at Cirrus Aircraft

**Version:** 2.1

## **1\. Objective & Philosophy**

The primary objective of this workflow is to enforce **environment consistency** to support our orchestration logic.

### **The Historical Problem**

Historically, **Lakeflow Connect (LLC) pipelines** were created exclusively in the Production environment. This created a critical "testing gap." Because these ingestion pipelines did not exist in Development or Test, we were unable to validate configuration changes to our table-driven architecture—specifically the logic controlling how data moves from Bronze to Silver.

### **The Requirement: Daisy-Chained Orchestration**

To support our data maturity, we are moving to a daisy-chained orchestration model:

1. **Bronze Ingestion** completes (via Lakeflow).  
2. **Trigger:** Success signal initiates the **Silver** table updates.  
3. **Trigger:** Silver completion initiates the **Gold** aggregation updates.

### **The Solution**

This orchestration chain cannot be tested if the upstream Bronze pipelines are missing from the lower environments. We use Databricks Asset Bundles (DABs) to ensure that **every pipeline** (including Lakeflow Connect ingestion) exists identically in Dev, Test, and Prod. This allows us to validate the full end-to-end trigger logic before it ever touches Production data.

### **Core Policies**

* **Configuration as Code:** The UI is for *deploying* and *monitoring*, not for *configuring*. All job settings (clusters, schedules, parameters) must be defined as code in YAML files.  
* **Immutable Promotion:** Code and configuration never originate in Test or Production. They are developed in the Development environment and promoted upstream without manual modification.  
* **Environment Locking:** Test and Production environments are set to "Production Mode" via DABs, making job configurations read-only in the UI to prevent drift.

**Required Training:**

**📺 Reference Video:** [Your Production and Test Environments Are Drifting Apart](https://www.youtube.com/watch?v=1qAtbwm1tT8)

*Source: The Data Engineering Channel (Gambill Data)*

## **2\. The Workflow Visualized**

The Databricks Asset Bundle acts as the control plane, utilizing a single configuration base (databricks.yml) to deploy to three distinct targets with different security contexts.

%%{init: {'theme': 'base', 'themeVariables': { 'primaryColor': '\#0056b3', 'edgeLabelBackground':'\#ffffff', 'tertiaryColor': '\#f4f4f4', 'fontFamily': 'Helvetica'}}}%%  
graph TD  
    subgraph Git\_Context \[Git Folder / IDE\]  
        YAML\[databricks.yml\<br/\>(The Source of Truth)\]  
        Code\[Source Code\<br/\>Notebooks & SQL\]  
    end

    subgraph Phase1 \[Phase 1: Development\]  
        style Phase1 fill:\#e6f7ff,stroke:\#0056b3  
        TargetDev\[Target: DEV\] \--\> Deploy1(UI: Click Deploy);  
        Deploy1 \--\> RunAsUser(Run as: Developer Identity);  
        RunAsUser \-- Iterate \--\> TargetDev  
    end

    subgraph Phase2 \[Phase 2: Test / Staging\]  
        style Phase2 fill:\#fffbe6,stroke:\#d4b106  
        Commit(Git Commit) \--\> TargetTest\[Target: TEST\];  
        TargetTest \--\> DeployTest(UI: Click Deploy);  
        DeployTest \--\> RunAsSP1(Run as: Service Principal\<br/\>State: LOCKED);  
    end

    subgraph Phase3 \[Phase 3: Production\]  
        style Phase3 fill:\#f6ffed,stroke:\#389e0d  
        Validation(Validation Success) \--\> TargetProd\[Target: PROD\];  
        TargetProd \--\> DeployProd(UI: Click Deploy);  
        DeployProd \--\> RunAsSP2(Run as: Service Principal\<br/\>State: LOCKED);  
    end

    YAML \-.-\>|Configures| Phase1  
    YAML \-.-\>|Configures| Phase2  
    YAML \-.-\>|Configures| Phase3  
      
    RunAsUser \--\> Commit  
    RunAsSP1 \--\> Validation

## **3\. Bundle Configuration Structure (databricks.yml)**

The databricks.yml file located at the root of your project is the brain of the operation. It defines *what* to deploy (via includes), *how* to configure it dynamically (via variables), and *where* to deploy it (via targets).

### **The Master Configuration Template**

*File: databricks.yml*

bundle:  
  name: cirrus-flight-telemetry-pipeline

\# \-------------------------------------------------------------------------  
\# INCLUDES: Modularity  
\# \-------------------------------------------------------------------------  
\# Imports all job/pipeline definitions from the resources folder.  
include:  
  \- resources/\*.yml

\# \-------------------------------------------------------------------------  
\# VARIABLES: Abstracted Configuration ("Knobs")  
\# \-------------------------------------------------------------------------  
\# Define defaults here. These are accessed in jobs using ${var.variable\_name}  
variables:  
  target\_catalog:  
    description: "The Unity Catalog where data lands per environment"  
    default: "cirrus\_dev\_catalog"  
  target\_schema:  
    description: "The schema (database) for this pipelines output"  
    default: "flight\_telemetry"  
  landing\_zone\_path:  
    description: "Cloud storage path for raw file ingestion"  
    default: "s3://cirrus-data-dev/landing/"

\# \-------------------------------------------------------------------------  
\# TARGETS: Environment Definitions  
\# \-------------------------------------------------------------------------  
targets:  
  \# \--- 1\. DEVELOPMENT (Sandbox) \---  
  dev:  
    mode: development \# Allows UI editing, prefixes jobs with \[dev user\]  
    default: true  
    workspace:  
      host: \[https://adb-DEV-WORKSPACE-ID.net\](https://adb-DEV-WORKSPACE-ID.net)  
    \# Override variables specifically for Dev  
    variables:  
      target\_catalog: "cirrus\_dev\_catalog"  
      landing\_zone\_path: "s3://cirrus-data-dev/landing/"

  \# \--- 2\. TEST (Staging / QA) \---  
  test:  
    mode: production \# LOCKS the job settings in the UI. Read-only.  
    workspace:  
      host: \[https://adb-TEST-WORKSPACE-ID.net\](https://adb-TEST-WORKSPACE-ID.net)  
      root\_path: /Shared/.bundle/test/${bundle.name}  
    run\_as:  
      service\_principal\_name: sp-cirrus-data-test-01 \# Runs as service identity  
    \# Override variables specifically for Test  
    variables:  
      target\_catalog: "cirrus\_test\_catalog"  
      landing\_zone\_path: "s3://cirrus-data-test/landing/"

  \# \--- 3\. PRODUCTION (Live) \---  
  prod:  
    mode: production \# LOCKS the job settings in the UI. Read-only.  
    workspace:  
      host: \[https://adb-PROD-WORKSPACE-ID.net\](https://adb-PROD-WORKSPACE-ID.net)  
      root\_path: /Shared/.bundle/prod/${bundle.name}  
    run\_as:  
      service\_principal\_name: sp-cirrus-data-prod-01 \# Runs as service identity  
    permissions:  
      \- level: CAN\_VIEW  
        group\_name: users  
      \- level: CAN\_MANAGE  
        group\_name: data-engineering-admins  
    \# Override variables specifically for Prod  
    variables:  
      target\_catalog: "cirrus\_prod\_catalog"  
      landing\_zone\_path: "s3://cirrus-data-prod/landing/"

## **4\. Defining Resources and Dependencies**

To achieve the "daisy-chain" effect (Bronze $\\rightarrow$ Silver $\\rightarrow$ Gold), we must explicitly define dependencies in the YAML.

### **A. Task Dependencies (Execution Order)**

*File: resources/flight\_etl\_job.yml*

resources:  
  jobs:  
    flight\_data\_process:  
      name: "Flight Data ETL \[${bundle.target}\]"  
      job\_clusters:  
        \- job\_cluster\_key: "standard\_cluster"  
          new\_cluster:  
            spark\_version: "13.3.x-scala2.12"  
            node\_type\_id: "Standard\_D4ds\_v5"  
            num\_workers: 2  
        
      tasks:  
        \# \--- TASK 1: INGEST (Bronze) \---  
        \- task\_key: "ingest\_bronze"  
          job\_cluster\_key: "standard\_cluster"  
          notebook\_task:  
            notebook\_path: ../src/1\_ingest\_bronze.py  
            \# Passing variables to the notebook as widgets/parameters  
            base\_parameters:  
              catalog: "${var.target\_catalog}"  
              source\_path: "${var.landing\_zone\_path}"  
          
        \# \--- TASK 2: PROCESS (Silver) \---  
        \# Only runs if Bronze Ingest succeeds  
        \- task\_key: "process\_silver"  
          \# This defines the execution order:  
          depends\_on:  
            \- task\_key: "ingest\_bronze"  
          job\_cluster\_key: "standard\_cluster"  
          notebook\_task:  
            notebook\_path: ../src/2\_process\_silver.py  
            base\_parameters:  
              catalog: "${var.target\_catalog}"

        \# \--- TASK 3: AGGREGATE (Gold) \---  
        \# Only runs if Silver Process succeeds  
        \- task\_key: "agg\_gold"  
          depends\_on:  
            \- task\_key: "process\_silver"  
          job\_cluster\_key: "standard\_cluster"  
          notebook\_task:  
            notebook\_path: ../src/3\_agg\_gold.py

### **B. Lakeflow Connect / DLT Example**

This definition ensures the Bronze ingestion pipeline exists in **all targets**, enabling the orchestration above.

*File: resources/lakeflow\_ingest.yml*

resources:  
  pipelines:  
    flight\_system\_ingest:  
      name: "Lakeflow Ingest \- Flight Ops \[${bundle.target}\]"  
        
      \# Dynamic Target Configuration using variables  
      catalog: "${var.target\_catalog}"  
      target: "${var.target\_schema}"  
        
      \# Cost Optimization: Run Single Node in Dev, Autoscaling in Test/Prod  
      development: ${bundle.target \== 'dev'}  
        
      channel: "PREVIEW"  
        
      \# Passing dynamic paths to the DLT configuration  
      configuration:  
        "cirrus.source.path": "${var.landing\_zone\_path}"  
        "cirrus.pipeline.env": "${bundle.target}"

## **5\. Execution Workflow (UI Steps)**

Engineers use the Databricks UI "Bundles" panel (right-hand sidebar in the code editor) for all deployment activities.

### **Phase 1: Development Loop (Iterate)**

*Goal: Rapid coding and validation in sandbox.*

1. Open databricks.yml in your Git Folder.  
2. Ensure the **Target** dropdown in the Bundles panel is set to **dev**.  
3. Click **Deploy**. (Validates YAML and pushes code to a hidden dev workspace location).  
4. Click **Play (Run)** in the panel to trigger the job immediately.  
5. **Verify Orchestration:** Ensure Task 1 (Bronze) successfully triggers Task 2 (Silver).

### **Phase 2: Promotion to Test (Validate)**

*Goal: Validation in a locked, production-mirror environment.*

1. **Commit all changes** to Git.  
2. Switch the **Target** dropdown to **test**.  
3. Click **Deploy**.  
   * *Note:* The Job created in the Test workspace is read-only in the UI because mode: production is set in the YAML.  
4. Trigger the run in Test. Verify the pipeline successfully orchestrates through the variables for the Test environment.

### **Phase 3: Production Release (Go Live)**

*Goal: Deployment to the live environment.*

1. Switch the **Target** dropdown to **prod**.  
2. Click **Deploy**.  
   * *Prerequisite:* You must have Admin permissions or be authorized to impersonate the Production Service Principal.  
3. Verify the job is active and scheduled in the Production Workflows UI.

## **6\. Troubleshooting Guide**

| Issue Symptoms | Likely Cause | Corrective Action |
| :---- | :---- | :---- |
| **Tasks run out of order** | Missing depends\_on in YAML | Review resources/job.yml. Downstream tasks must explicitly list their dependencies in the depends\_on: block. |
| **"Target not found"** | YAML Syntax Error | Ensure the targets: block in databricks.yml explicitly defines dev, test, and prod. |
| **Settings Locked in UI** | Working as intended | The target is in mode: production. To change settings, update the YAML file and redeploy. Do not attempt UI hotfixes. |
| **Permission Denied** | Missing Service Principal Access | Ensure your user account is allowed to deploy as the service\_principal\_name defined in the target. |
| **New Job Missing** | Missing include | Ensure databricks.yml has include: \- resources/\*.yml and the file is in the correct folder. |
