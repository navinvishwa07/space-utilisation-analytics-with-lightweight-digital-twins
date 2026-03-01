# AI Development Rules

## 1. Code Discipline

No hardcoded paths  
No silent exception swallowing  
All inputs validated  
All errors logged  

---

## 2. ML Rules

Use interpretable model  
Log model version  
Document feature assumptions  
Allow retraining entry point  

No deep learning black boxes.

---

## 3. Matching Rules

Never bypass constraint checks  
Never allow overlapping allocation  
Always validate capacity  
Fallback mechanism required  

---

## 4. Security

Simple single-token admin authentication  
Bearer session token returned on login (token differs from admin secret)  
Admin secret validated via constant-time comparison (secrets.compare_digest)  
Do not implement multi-tenant or role-based access control  
Do not simulate payment or billing logic  

---

## 5. Scope Enforcement

Do not introduce marketplace features  
Do not add production-grade auth  
Do not expand to multi-tenant SaaS  
