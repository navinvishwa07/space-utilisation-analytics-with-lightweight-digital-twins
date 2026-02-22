# Shared Infrastructure Exchange Twin (SIET)

## 1. Overview

SIET is a predictive allocation engine that models institutional spaces as digital twins, forecasts idle availability, and optimally matches demand using constraint-based optimization.

This MVP focuses on intelligence and allocation — not full marketplace infrastructure.

---

## 2. Problem Statement

Institutional infrastructure (classrooms, halls, labs) is frequently underutilized.

Existing systems:
- Show availability statically
- Do not predict future idle slots
- Do not optimize allocation
- Do not simulate utilization improvement

There is no lightweight predictive allocation engine that increases utilization proactively.

---

## 3. Core Value Proposition

Predict idle capacity  
Optimize allocation  
Simulate improvement  

---

## 4. Hackathon MVP Scope (Strict)

### Included

• Digital twin modeling (rooms, slots, constraints)  
• Idle probability prediction (ML baseline model)  
• Constraint-based matching engine  
• Simulation engine (before vs after utilization)  
• Simple admin interface (Streamlit)  
• Structured logging  

### Explicitly Excluded

• Real payments  
• JWT authentication  
• IoT integration  
• Real-time streaming  
• Multi-tenant production hosting  
• CI/CD pipelines  

---

## 5. Users (MVP Context)

Single institutional admin using system locally.

---

## 6. Functional Requirements

FR1: System loads space inventory dataset  
FR2: System trains idle probability model  
FR3: System predicts idle score per slot  
FR4: System matches requests using constraints  
FR5: System prevents double booking  
FR6: System simulates utilization improvement  
FR7: System logs allocation decisions  

---

## 7. Constraints

Capacity must satisfy request  
No overlapping time slots  
One allocation per slot  
Priority weight impacts objective score  

---

## 8. Success Metrics

Utilization improvement %  
Allocation success rate  
Conflict-free booking validation  

---

## 9. Risks & Mitigation

Solver infeasibility → fallback greedy allocator  
ML overfitting → simple interpretable baseline  
Scope creep → enforce strict MVP boundary  