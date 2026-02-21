---
title: "SOC 2-Aligned Azure Networking Security Controls (Typical)"
version: "1.0"
last_updated: "2026-01-11"
intended_use: "Knowledge base document for vector DB ingestion and RAG Q&A"
tags:
  - soc2
  - azure
  - networking
  - security-controls
  - nsg
  - firewall
  - private-link
  - ddos
  - waf
  - logging
---

# SOC 2-aligned Azure Networking Security Controls (Typical)

This document lists **typical security controls** organizations implement for **Azure networking** and maps them to **SOC 2 Trust Services Criteria (TSC)** themes.

It is written for **knowledge base ingestion** into a vector database and use with a **RAG** system (e.g., “what evidence proves network segmentation?”).

> Note: SOC 2 mappings below are **examples** (commonly aligned to the *Security / Common Criteria* domain). Confirm final mapping and wording with your compliance team/auditor.

## Scope

Applies to Azure environments hosting production workloads, including (as relevant):
- Virtual Networks (VNets), subnets, route tables (UDRs)
- Network Security Groups (NSGs), Application Security Groups (ASGs)
- Azure Firewall, Firewall Policy, and network rules
- Application Gateway / WAF, Front Door / WAF (if used)
- DDoS Protection Standard (if used)
- Azure Private Link / Private Endpoints, Private DNS
- Load Balancers, NAT Gateway
- VPN Gateway / ExpressRoute (hybrid connectivity)
- Azure Bastion / privileged access paths
- DNS (Azure DNS / Private DNS Zones)
- Network monitoring and logging (NSG flow logs, Firewall logs, WAF logs, etc.)

## Control design principles

- **Deny by default** for inbound traffic and administrative access.
- **Least privilege** for network paths and identity permissions.
- **Segmentation** between tiers (web/app/data) and between environments (dev/test/prod).
- **Defense-in-depth** using layered controls (NSGs + Firewall + WAF + Private Endpoints).
- **Auditability** via centralized logging, alerting, and evidence retention.

---

# Control catalog

Each control includes:
- **Control statement**: what you commit to doing
- **Azure implementation guidance**: common Azure services/settings
- **Evidence examples**: what to collect during audits

## A. Governance & asset inventory (typical SOC 2 alignment: Security / CC1, CC2)

### NET-GOV-01 — Network architecture standards
**Control statement**
- Document and maintain Azure network architecture standards for segmentation, ingress/egress, and administrative access.

**Azure implementation guidance**
- Define reference architectures (hub-and-spoke, landing zones) and standard subnet patterns.
- Standardize naming, tagging, and baseline configurations.

**Evidence examples**
- Approved network architecture diagrams.
- Published standards/baselines (wiki/markdown/policy docs).
- Change logs showing periodic reviews.

### NET-GOV-02 — Network asset inventory and ownership
**Control statement**
- Maintain an inventory of network resources and assign accountable owners.

**Azure implementation guidance**
- Use tags for `Owner`, `Environment`, `DataClassification`.
- Use Azure Resource Graph queries to enumerate VNets, NSGs, firewalls, gateways.

**Evidence examples**
- Resource inventory exports.
- Tag compliance reports.

---

## B. Network segmentation & access control (typical SOC 2 alignment: Security / CC6)

### NET-SEG-01 — Environment isolation (prod vs non-prod)
**Control statement**
- Isolate production networks from non-production to prevent unauthorized lateral movement.

**Azure implementation guidance**
- Separate subscriptions/management groups and/or separate VNets.
- Restrict peering; if peered, enforce strict UDR/NSG rules.

**Evidence examples**
- Subscription hierarchy and network topology diagrams.
- VNet peering configurations.
- NSG rule exports showing restricted inter-environment traffic.

### NET-SEG-02 — Tier segmentation (web/app/data)
**Control statement**
- Segment application tiers and restrict traffic between tiers to required protocols/ports only.

**Azure implementation guidance**
- Use subnets per tier, NSGs per subnet, and optionally ASGs for workload grouping.
- Consider Azure Firewall for centralized east-west policy enforcement.

**Evidence examples**
- NSG rules demonstrating allowed flows only.
- Firewall Policy rule collections.

### NET-ACC-01 — Deny-by-default inbound access
**Control statement**
- Enforce deny-by-default inbound network access and explicitly allow only required traffic.

**Azure implementation guidance**
- NSG inbound default `DenyAllInbound` plus minimal allow rules.
- Prefer WAF/Application Gateway/Front Door for public apps; avoid direct VM public exposure.

**Evidence examples**
- NSG configuration exports.
- List of public IP assignments and exception approvals.

### NET-ACC-02 — Administrative access path controls
**Control statement**
- Restrict administrative access (e.g., SSH/RDP/Kubernetes admin endpoints) to approved secure access paths.

**Azure implementation guidance**
- Use Azure Bastion, Just-In-Time access (Defender for Cloud), VPN/ExpressRoute.
- Block direct SSH/RDP from the Internet.
- For AKS: restrict API server access (private cluster or authorized IP ranges).

**Evidence examples**
- Bastion configuration.
- NSG rules showing no inbound SSH/RDP from `0.0.0.0/0`.
- AKS API server settings screenshot/export.

### NET-ACC-03 — Network-level least privilege for service-to-service traffic
**Control statement**
- Limit service-to-service network access to the minimum required.

**Azure implementation guidance**
- Use NSGs/ASGs and service tags.
- Prefer Private Endpoints for PaaS services and disable public network access where possible.

**Evidence examples**
- Private Endpoint inventories.
- PaaS “public access disabled” settings.

---

## C. Ingress security (typical SOC 2 alignment: Security / CC6, CC7)

### NET-ING-01 — Web application firewall (WAF)
**Control statement**
- Protect internet-facing HTTP(S) applications using a WAF configured to detect/block common attacks.

**Azure implementation guidance**
- Azure Application Gateway WAF or Azure Front Door WAF.
- Enable managed rulesets; tune exclusions with documented risk acceptance.

**Evidence examples**
- WAF policy settings and rule status.
- WAF logs showing detections/blocks.

### NET-ING-02 — TLS and secure cipher policy
**Control statement**
- Enforce TLS for ingress endpoints and maintain secure TLS configurations.

**Azure implementation guidance**
- Terminate TLS at Front Door/App Gateway; use Key Vault certificates.
- Redirect HTTP → HTTPS.

**Evidence examples**
- Listener and certificate configuration exports.
- Periodic TLS scan results.

### NET-ING-03 — DDoS protection for critical public endpoints
**Control statement**
- Implement DDoS protections for critical internet-facing workloads.

**Azure implementation guidance**
- Enable DDoS Protection Standard on the VNet (or protected public IPs).
- Establish runbooks for DDoS events and contact procedures.

**Evidence examples**
- DDoS plan configuration.
- Incident runbooks and alert rules.

---

## D. Egress control & exfiltration prevention (typical SOC 2 alignment: Security / CC6, CC7, Confidentiality)

### NET-EGR-01 — Centralized egress via firewall/NAT
**Control statement**
- Route outbound traffic through controlled egress points and monitor/limit destinations.

**Azure implementation guidance**
- Use Azure Firewall and UDRs to force egress.
- Use NAT Gateway for predictable outbound IPs.

**Evidence examples**
- Route table exports showing forced tunneling to firewall.
- Azure Firewall logs and policies.

### NET-EGR-02 — Outbound allow-listing for sensitive workloads
**Control statement**
- Where required by data sensitivity, restrict outbound traffic to approved destinations.

**Azure implementation guidance**
- Firewall application rules with FQDN tags/allow lists.
- Deny all other outbound categories.

**Evidence examples**
- Firewall policy rule collections.
- Approved destination lists and review records.

---

## E. Private connectivity & PaaS hardening (typical SOC 2 alignment: Security / CC6, Confidentiality)

### NET-PRV-01 — Private Endpoints for critical PaaS services
**Control statement**
- Use private connectivity for critical PaaS services and disable public access where feasible.

**Azure implementation guidance**
- Azure Private Link + Private Endpoints for Storage, Key Vault, SQL, etc.
- Configure Private DNS Zones for name resolution.

**Evidence examples**
- Private Endpoint inventory.
- PaaS networking settings showing “Public network access: Disabled” (where applicable).
- Private DNS zone records.

### NET-PRV-02 — Restrict PaaS access by network rules
**Control statement**
- Restrict PaaS access using network rules (VNet integration, firewall rules, service endpoints where used).

**Azure implementation guidance**
- Storage account network rules, Key Vault firewall settings, SQL server firewall.

**Evidence examples**
- PaaS network ACL exports.
- Exception approvals for temporary public access.

---

## F. Logging, monitoring, and incident response (typical SOC 2 alignment: Security / CC7)

### NET-LOG-01 — Centralized network logging
**Control statement**
- Collect and retain network security logs centrally to support detection, investigation, and audit.

**Azure implementation guidance**
- Send NSG Flow Logs (Traffic Analytics), Firewall logs, WAF logs to Log Analytics / Sentinel.
- Standardize diagnostic settings via policy.

**Evidence examples**
- Diagnostic settings showing log destinations.
- Log Analytics workspace configuration.
- Data retention settings.

### NET-LOG-02 — Alerting on suspicious network events
**Control statement**
- Alert on suspicious or high-risk network events and investigate per incident procedures.

**Azure implementation guidance**
- Sentinel analytics rules for: denied spikes, geo anomalies, WAF blocks, firewall deny bursts.
- Action Groups + on-call routing.

**Evidence examples**
- Alert rule definitions.
- Incident tickets and post-incident reviews.

---

## G. Change management & configuration assurance (typical SOC 2 alignment: Security / CC8)

### NET-CHG-01 — Controlled changes to network security rules
**Control statement**
- Changes to NSGs, firewall rules, WAF policies, and route tables follow change management, review, and approval.

**Azure implementation guidance**
- Use IaC (Bicep/Terraform) and pull requests.
- Require approvals for production changes; separate roles for request vs approve.

**Evidence examples**
- PRs with approvals and linked change tickets.
- Deployment logs (CI/CD).

### NET-CFG-01 — Policy-based enforcement of networking baselines
**Control statement**
- Enforce baseline network security configurations using automated policy controls.

**Azure implementation guidance**
- Azure Policy initiatives: restrict public IPs, require diagnostics, require TLS, restrict peering.
- Defender for Cloud recommendations as secondary signal.

**Evidence examples**
- Policy assignments and compliance reports.
- Exceptions (waivers) with expiration dates.

---

## H. Availability & resilience (typical SOC 2 alignment: Availability)

### NET-AVL-01 — Redundant connectivity for critical services
**Control statement**
- Design network connectivity to avoid single points of failure for critical workloads.

**Azure implementation guidance**
- Zone-redundant gateways (where supported).
- Multiple instances for WAF/App Gateway and firewall.

**Evidence examples**
- Architecture diagrams and SKU/zone settings.
- Resiliency test records.

### NET-AVL-02 — Capacity monitoring for network components
**Control statement**
- Monitor capacity and performance of critical network components and scale as needed.

**Azure implementation guidance**
- Metrics/alerts for App Gateway capacity units, Firewall throughput, SNAT port exhaustion.

**Evidence examples**
- Monitoring dashboards and alert configurations.

---

# Suggested RAG prompts (for testing)

Use these questions to validate retrieval quality after ingesting this document:

1. “What controls prevent direct SSH/RDP from the internet?”
2. “How do we prove network segmentation between prod and non-prod?”
3. “What evidence shows we log NSG flows and firewall denies centrally?”
4. “How is outbound traffic restricted to approved destinations?”
5. “When should we use Private Endpoints and what evidence proves they’re in place?”

# Glossary

- **NSG**: Network Security Group
- **ASG**: Application Security Group
- **UDR**: User-Defined Route
- **WAF**: Web Application Firewall
- **Private Link / Private Endpoint**: Private access to Azure PaaS services over a private IP
- **Sentinel**: Microsoft’s SIEM/SOAR
