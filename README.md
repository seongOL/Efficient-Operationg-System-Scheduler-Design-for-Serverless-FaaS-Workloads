
# Efficient Operating System Scheduler Design for Serverless (FaaS) Workloads  
Custom Scheduler for OpenFaaS using Azure Functions Trace 2019

---

## Overview

This repository contains the implementation of a custom scheduler designed to improve performance in serverless Function-as-a-Service (FaaS) environments.  
The scheduler operates at the gateway/request level, without modifying the Linux kernel, and aims to:

- Reduce excessive Context Switching inside function containers  
- Prevent slow/straggler functions from degrading system-wide performance  
- Provide consistent scheduling efficiency across highly irregular workloads

---

## Features

### EWMA-based Latency Tracking  
Each function instance maintains its own exponentially weighted moving average (EWMA) to detect slow executions in real time.

### Slow Function Quarantine  
Functions whose estimated latency exceeds a threshold are temporarily excluded from scheduling decisions.

### Hedge Request (Speculative Redundancy)  
If a request is predicted to be slow, a duplicate request is sent to a faster candidate function.

### Token-Bucket Concurrency Control  
Prevents queue buildup by limiting per-function concurrent executions.

### Self-Healing Mechanism  
Quarantined functions automatically rejoin once their delay state recovers.

---

## System Architecture

- trace_parser.py : converts Azure dataset entries into inter-arrival + execution patterns  
- workload_replayer.py : replays the workload to the OpenFaaS gateway  
- custom_scheduler.py : handles request dispatching logic (EWMA, quarantine, hedged execution, token bucket)

---

## Dataset: Azure Functions Trace 2019

This project uses the Microsoft Azure Functions Trace 2019 dataset provided in:

> M. Shahrad et al.,  
> *“Serverless in the Wild: Characterizing and Optimizing the Serverless Workload at a Large Cloud Provider,”*  
> USENIX ATC, 2020.

Dataset used strictly for **academic and research purposes**.

---

### Code Origin and License Compliance

This project uses and modifies code from the following open-source project:

**hybrid-scheduler**  
https://github.com/ZhaoNeil/hybrid-scheduler  
Licensed under the **BSD 3-Clause License**

Modified portions are included mainly in `trace_parser.py` and related workload processing logic.  
All required copyright and license notices from the BSD 3-Clause License are preserved.
