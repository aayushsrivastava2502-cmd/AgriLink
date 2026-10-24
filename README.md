# AgriLink AI
**A Direct Farmer-to-Customer Marketplace with Smarter Pricing, Local Sourcing, and Transport Cost Optimization**

B.Tech Computer Science mini project built with Python Flask, SQLite, Pandas, scikit-learn, Leaflet.js, and OpenStreetMap.

> **Currency Invariant:** Every price, order subtotal, delivered total, transport rate, and delivery share in AgriLink AI is strictly calculated and displayed in **Indian Rupees (₹)**, with unit prices expressed in **₹/kg** and distances in **kilometres (km)**.

---

## 1. Project Overview

AgriLink AI connects smallholder farmers directly with buyers (consumers, households, and local retailers), bypassing exploitative intermediary commissions. The platform features:

1. **Direct Marketplace:** Crop listings with high-resolution details, category filters, and live order management.
2. **AI Price Guidance:** A Smart Price Estimator comparing farmer asking prices with historical mandi benchmarks in ₹/kg.
3. **Geospatial Discovery:** Interactive Leaflet.js / OpenStreetMap map visualizing local farmers and aggregation hubs around Greater Noida, Uttar Pradesh.
4. **Transport Cost Optimization:** A comprehensive logistics management module addressing fragmented agricultural transit via shared delivery grouping, multi-buyer group pools, route stop optimization, and regional collection point hubs.

---

## 2. Problem Statement & Motivation

Smallholder agricultural logistics suffers from critical structural inefficiencies:
- **High Last-Mile Freight:** Transporting small quantities individually results in prohibitive per-kg transport expenses.
- **Empty Return Legs:** Farmers making individual delivery trips return with empty vehicles.
- **Fragmented Buyer Demand:** Multiple buyers living in the same residential sector or neighborhood order independently, causing duplicate transit trips.
- **Opacity in Delivered Costs:** Buyers often evaluate farm produce strictly on product price without transparent visibility into transport and delivered totals.

---

## 3. Core Capabilities & Feature Matrix

| Functional Area | Implemented Capabilities |
|---|---|
| **Authentication & RBAC** | Session-based authentication, PBKDF2 password hashing, CSRF protection, and role-based access control (`farmer` vs `buyer`). |
| **Farmer Operations** | Add, edit, manage crop listings; upload images; toggle active/sold-out; accept, reject, complete orders; create and manage shared trips; confirm group pools. |
| **Buyer Operations** | Marketplace search and filtering (crop, category, location, ₹ range, quality); sort by price, recency, or distance; submit delivery orders; view allocated trip shares; join group ordering pools. |
| **Smart Price Estimator** | Trained `RandomForestRegressor` when sufficient historical mandi data exists; statistical recent averages; labelled demonstration mode when data is unavailable. Never claims synthetic data is live. |
| **Nearby Farmer Matching** | Haversine distance calculation, inventory sufficiency check, side-by-side product cost vs transport cost breakdown. |
| **Shared Transportation** | Cluster eligible orders (same origin/hub and delivery vicinity); propose multi-stop shared trips; allocate costs via transparent formulas; display buyer savings. |
| **Group Ordering Pools** | Multi-buyer pooled demand for single listings; automated stock checks; bulk delivery savings comparison; atomic stock deduction on pool confirmation. |
| **Route Planning** | Interactive Leaflet delivery planner; Nearest Neighbour Traveling Salesperson heuristic reordering; transparent straight-line distance approximation labels. |
| **Collection Point Hubs** | Regional aggregation hubs (Dadri, Pari Chowk, Surajpur, Jewar); visual map pins; direct vs hub delivery logistics cost comparisons. |
| **Cost Comparison Dashboard** | Live logistics metrics; interactive cost simulator comparing separate vs shared delivery; configurable transport rate (₹/km). |
| **Bilingual Localization (English & हिन्दी)** | Full bilingual UI with navbar switcher (`English | हिन्दी`); seamless switching without session logout; persistent language in session; Devanagari typography (`Noto Sans Devanagari`); invariant ₹ currency, kg, and km units. |

---

## 4. Transport Cost Optimization Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           AgriLink AI Frontend                              │
│       (Jinja2 Templates + Leaflet.js / OpenStreetMap + Bootstrap CSS)       │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ HTTP / Form Post / JSON API
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                            Flask Application Core                           │
│  routes/transport.py · routes/orders.py · routes/farmer.py · routes/main.py │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Business Logic & Optimization
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                    Transport Optimizer Service Layer                        │
│                (services/transport_optimizer_service.py)                     │
│  ├─ route_distance_km() & optimize_delivery_route() (Nearest Neighbour TSP) │
│  ├─ allocate_shared_costs() (Proportional Weight & Standalone Methods)     │
│  ├─ find_eligible_orders_for_shared_trip() & calculate_shared_proposal()   │
│  ├─ create_and_persist_shared_trip() & update_shared_trip_status()         │
│  ├─ create_group_pool(), join_group_pool(), confirm_group_pool()           │
│  └─ compare_direct_vs_hub() & get_transport_overview_metrics()             │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Transactions & Integrity (PRAGMA foreign_keys=ON)
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                            SQLite Database Engine                           │
│                             (instance/agrilink.db)                          │
│  • users               • crop_listings          • order_requests            │
│  • collection_points   • shared_trips           • shared_trip_orders        │
│  • group_order_pools   • group_order_members    • price_history             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Mathematical Formulations & Optimization Methods

### 5.1 Distance Calculation (Haversine Formula)
Distances are computed using the spherical Haversine formula over the WGS84 Earth ellipsoid ($R = 6371.0\text{ km}$):
$$\Delta\sigma = 2 \arcsin \sqrt{\sin^2\left(\frac{\Delta\phi}{2}\right) + \cos\phi_1 \cos\phi_2 \sin^2\left(\frac{\Delta\lambda}{2}\right)}$$
$$d = R \cdot \Delta\sigma$$

> **Transparent Assumption Disclaimer:** In the absence of an integrated road-network routing engine, straight-line Haversine distance is used as an approximation. The user interface explicitly labels straight-line distance approximations to avoid misleading users into believing it represents exact odometer road distance.

### 5.2 Multi-Stop Route Optimization (Nearest Neighbour TSP Heuristic)
For delivery trips involving multiple stops $S = \{s_1, s_2, \dots, s_n\}$ starting from origin $O$:
1. Current position begins at $P_0 = O$.
2. Iteratively select next unvisited stop $s^* \in S_{\text{unvisited}}$ minimizing $d(P_{\text{current}}, s^*)$.
3. Update $P_{\text{current}} = s^*$ and append to itinerary until all stops are visited.
4. Total optimized route distance:
   $$D_{\text{shared}} = d(O, s_{\pi(1)}) + \sum_{k=1}^{n-1} d(s_{\pi(k)}, s_{\pi(k+1)})$$
5. Standalone separate delivery distance sum:
   $$D_{\text{standalone}} = \sum_{i=1}^n d(O, s_i)$$

### 5.3 Shared Cost Allocation Models
AgriLink AI implements two transparent cost allocation methods, computed with exact Python `Decimal` arithmetic and penny reconciliation:

#### Method A: Proportional by Weight
Used when vehicle capacity and fuel consumption are primarily driven by cargo mass:
$$C_i = C_{\text{total}} \times \frac{w_i}{\sum_{j=1}^n w_j}$$
Where $w_i$ is the quantity in kg of order $i$, and $C_{\text{total}}$ is the total shared trip cost.

#### Method B: Proportional by Standalone Cost
Used when individual stops have widely varying delivery distances:
$$C_i = C_{\text{total}} \times \frac{S_i}{\sum_{j=1}^n S_j}$$
Where $S_i = \max(d(O, s_i) \times \text{rate}, \text{min\_charge})$ is buyer $i$'s standalone delivery cost.

**Reconciliation Invariant:** Rounding discrepancies are automatically credited/debited to the largest share so that:
$$\sum_{i=1}^n C_i \equiv C_{\text{total}}$$

---

## 6. Database Schema Additions

The database schema extends `instance/agrilink.db` with five dedicated tables and automatic migration of the `order_requests` table:

1. **`collection_points`**: Regional aggregation hubs.
   - `id`, `name`, `code`, `address`, `city`, `state`, `latitude`, `longitude`, `contact_phone`, `operating_hours`, `is_active`, `created_at`.
2. **`shared_trips`**: Grouped multi-stop delivery routes.
   - `id`, `trip_code`, `farmer_id` (FK), `collection_point_id` (FK, nullable), `status` (`proposed`, `confirmed`, `dispatched`, `completed`, `cancelled`), `total_distance_km`, `transport_rate_per_km`, `total_transport_cost`, `allocation_method`, `created_at`, `dispatched_at`, `completed_at`.
3. **`shared_trip_orders`**: Many-to-many junction mapping orders to trips with allocated costs.
   - `id`, `shared_trip_id` (FK), `order_id` (FK), `stop_sequence`, `standalone_cost`, `allocated_share`, `estimated_savings`, `created_at`.
4. **`group_order_pools`**: Pooled buyer demand for single crop listings.
   - `id`, `pool_code`, `listing_id` (FK), `target_quantity_kg`, `current_quantity_kg`, `price_per_kg`, `status` (`open`, `confirmed`, `cancelled`), `delivery_area`, `delivery_lat`, `delivery_lng`, `estimated_transport_cost`, `created_at`, `expires_at`.
5. **`group_order_members`**: Participating buyers within a group pool.
   - `id`, `pool_id` (FK), `buyer_id` (FK), `quantity_kg`, `product_cost`, `allocated_transport_share`, `total_cost`, `joined_at`.
6. **`order_requests` Schema Migration**:
   - Added `delivery_address` (TEXT), `delivery_lat` (REAL), and `delivery_lng` (REAL) with backward compatibility for legacy records.

---

## 6. Bilingual Architecture (English & हिन्दी)

AgriLink AI provides a complete bilingual localization engine designed specifically for Indian farmers and buyers:

### 6.1 Centralized Translation Layer (`services/i18n.py`)
- **Supported Languages:** `en` (English) and `hi` (हिन्दी / Hindi).
- **Translation Registry:** Over 150 comprehensive domain phrases covering agriculture, logistics, statuses, forms, and validation alerts in natural rural Hindi.
- **Jinja2 Helpers & Globals:** `_()`, `t()`, `current_lang`, and Devanagari date filter (`fmt_date`).
- **Client-Side Localization:** Dynamic JSON dictionary injected into `window.AGRI_I18N` to translate Leaflet popup markers, geolocator status prompts, and Chart.js labels without breaking JavaScript execution.

### 6.2 Session Persistence & Safe Switching
- **Navbar Switcher:** Accessible pill toggle (`English | हिन्दी`) on every page.
- **Safe Language Endpoint:** `/set-language` route supports both POST and GET with open-redirect validation preventing off-site redirection.
- **Session Invariance:** Switching languages maintains active shopping carts, order forms, and filter states without logging out the user. Authentication actions (`login`, `register`, `logout`) preserve user language preference.

### 6.3 Currency & Metric Invariance
- **Indian Rupees (₹):** Currency symbols remain strictly ₹ across English and Hindi.
- **Metric Standards:** Weights remain in kilograms (`kg`) and distances in kilometres (`km`).
- **Devanagari Typography:** Clean responsive rendering with Google Fonts `Noto Sans Devanagari` and robust system font fallbacks.

---

## 7. Windows PowerShell Setup & Execution Guide

### Prerequisites
- Windows 10/11 with PowerShell 5.1+ or PowerShell 7+
- Python 3.10, 3.11, or 3.12 installed and added to `PATH`

### 7.1 Clone and Environment Setup
```powershell
# 1. Navigate to the project directory
cd c:\Users\aayus\Downloads\agrilink-ai\agrilink-ai

# 2. (Optional) Create and activate a Python virtual environment
python -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1

# 3. Install core dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 7.2 Database Initialization & Seeding
```powershell
# 4. Initialize schema (creates all core and transport optimization tables)
python -m flask --app app init-db

# 5. Seed regional collection hubs, demo farmers, listings, and orders
python -m flask --app app seed-db
```

> **Note on Fresh Reset:** To reset the database to a clean demonstration state at any time:
> ```powershell
> python -m flask --app app seed-db --reset
> ```

### 7.3 Running the Automated Test Suite
Execute the comprehensive test suite (46 automated unit, integration, and bilingual i18n tests):
```powershell
python -m unittest discover -s tests -v
```

### 7.4 Launching the Application
```powershell
# Start the AgriLink AI local server
python app.py
```
Open your browser and navigate to:
**http://127.0.0.1:5000**

---

## 8. Demonstration Accounts

All demo accounts share the password: `Demo@1234`

| Role | Email | Name | Fictional Location |
|---|---|---|---|
| **Farmer** | `farmer1@demo.agrilink.test` | Ramesh Kumar | Dadri, Greater Noida |
| **Farmer** | `farmer2@demo.agrilink.test` | Sunita Devi | Jewar, Greater Noida |
| **Farmer** | `farmer3@demo.agrilink.test` | Harish Sharma | Surajpur, Greater Noida |
| **Farmer** | `farmer4@demo.agrilink.test` | Anjali Verma | Pari Chowk, Greater Noida |
| **Farmer** | `farmer5@demo.agrilink.test` | Devendra Singh | Dankaur, Greater Noida |
| **Farmer** | `farmer6@demo.agrilink.test` | Babita Patel | Bilaspur, Greater Noida |
| **Buyer** | `buyer1@demo.agrilink.test` | Priya Sharma | Alpha 1, Greater Noida |
| **Buyer** | `buyer2@demo.agrilink.test` | Amit Patel | Beta 2, Greater Noida |
| **Buyer** | `buyer3@demo.agrilink.test` | Neha Gupta | Omega 1, Greater Noida |

---

## 9. End-to-End Workflow Verification Guides

### Workflow 1: Standard Marketplace & Order Lifecycle
1. **Farmer Listing:** Log in as `farmer1@demo.agrilink.test`. Navigate to **Listings → Add Listing**. Enter "Organic Wheat", 500 kg, ₹28/kg. Listing appears immediately in the active catalog.
2. **Buyer Discovery:** Log in as `buyer1@demo.agrilink.test`. Go to **Marketplace**, filter by "Wheat", and click on the listing.
3. **Order Submission:** Enter 50 kg and provide a delivery address (e.g., "Alpha 1, Greater Noida"). The system calculates a product subtotal of ₹1,400. Click **Send Order Request**.
4. **Farmer Acceptance:** Switch to `farmer1`. Open **Farmer Dashboard → Order Requests**. Click **Accept Order**. The listing's available stock atomically decrements from 500 kg to 450 kg.
5. **Buyer Tracking:** Switch to `buyer1`. Open **Orders**. Status reflects **Accepted**. Once delivered, the farmer marks it **Completed**.

### Workflow 2: Transport Optimization & Shared Delivery Trips
1. **Locate Nearby Farmers:** Go to **Nearby Farmers**. Select your delivery sector (e.g., "Alpha 1"). Observe the distance ranking and delivered cost breakdown (crop cost + transport cost in ₹).
2. **Propose a Shared Trip:** Log in as `farmer4@demo.agrilink.test`. Navigate to **Transport Optimizer → Shared Trips → Propose Shared Trip**.
3. **Select Compatible Orders:** Choose eligible accepted orders destined for the same sector. Select an allocation method (**Proportional by Weight** or **Proportional by Standalone Cost**).
4. **Inspect Route & Allocation:** The system visualizes the multi-stop route on OpenStreetMap, orders the stops via Nearest Neighbour TSP, calculates total trip cost, and displays each buyer's allocated share alongside their estimated savings in ₹.
5. **Confirm and Dispatch:** Click **Create Shared Delivery Trip**. The trip is persisted with a unique code (e.g., `TRIP-20261024-XXXX`). Participating buyer order cards immediately show their shared delivery badge and reduced delivery share.

### Workflow 3: Group Ordering Pool
1. **Explore Group Pools:** Navigate to **Transport Optimizer → Group Pools**.
2. **Join / Create a Pool:** Open a listing or open pool for "Basmati Rice". Enter 25 kg to join the pool.
3. **Demand Aggregation:** The pool progress bar updates showing current vs target kg.
4. **Pool Confirmation:** Once target quantity is achieved, the farmer reviews and confirms the pool. The total quantity is atomically deducted from listing stock in a single transaction.

---

## 10. Automated Test Results Summary

The automated test suite verifies all functional invariants, security guards, mathematical formulas, database integrity, and bilingual internationalization:

```text
Ran 46 tests in 29.3s
OK
```

### Verified Test Categories:
- **`AccessControlTests` (1 test):** RBAC enforcement; blocks unauthorized role access to farmer/buyer routes.
- **`AuthTests` (4 tests):** Registration, login, logout, password hashing, open redirect prevention, CSRF validation.
- **`DistanceTests` (2 tests):** Haversine distance calculations and ₹/km rate application.
- **`ErrorTests` (1 test):** Custom 404/500 error handling with clean UI responses.
- **`EstimatorTests` (4 tests):** Machine learning pipeline guards, bad CSV rejection, demo mode labeling, and synthetic training evaluation.
- **`ListingTests` (3 tests):** Crop listing CRUD, farmer ownership guards, image extension validation.
- **`MapTests` (1 test):** Leaflet map coordinate emission and popup data safety.
- **`MarketplaceTests` (3 tests):** Search filters, SQL injection prevention, parameter validation, nearest-farmer sorting.
- **`MoneyTests` (2 tests):** Decimal rounding, ₹ currency formatting, unit price assertions.
- **`OrderTests` (7 tests):** Stock deduction atomicity, overselling prevention, status transitions, SQLite persistence across restarts.
- **`WorkflowAndIntegrationTests` (2 tests):** Complete end-to-end farmer-to-buyer transaction lifecycle.
- **`RouteOptimizationAndDistanceTests` (3 tests):** Route distance summation, missing coordinate handling, Nearest Neighbour heuristic ordering.
- **`CostAllocationTests` (2 tests):** Proportional-by-weight and proportional-by-standalone allocation with penny reconciliation.
- **`GroupOrderingPoolTests` (1 test):** Pool creation, participant joining, capacity guards, and confirmation stock deduction.
- **`SharedTransportationWorkflowTests` (1 test):** Shared trip creation, allocation persistence, and status lifecycle.
- **`CollectionPointAndApiTests` (3 tests):** Regional collection point seeding, direct vs hub comparison, JSON optimization APIs.
- **`I18nTests` (6 tests):** Bilingual language switching, safe open-redirect guards, session persistence through login/logout, Hindi UI validation across pages, client-side JS payload localization, and currency/unit invariance.

---

## 11. Implemented Features vs Illustrative Prototypes

To maintain strict academic and professional integrity, AgriLink AI distinguishes between fully verified production-grade logic and illustrative demonstration components:

### Fully Working Features
- **Database & Data Layer:** Parameterized SQLite database with atomic transactions, foreign keys, and persistent storage across server restarts.
- **Authentication & Security:** Real password hashing, CSRF token validation, role-based decorators, and SQL injection prevention.
- **Marketplace & Orders:** Full CRUD for listings, search/filtering, atomic stock deduction on order acceptance and group pool confirmation.
- **Transport Optimizer Service:** Real Haversine calculations, Nearest Neighbour TSP route sequencing, multi-stop distance computation, and Decimal-based cost allocation formulas with penny reconciliation.
- **Interactive Geospatial Visualization:** Leaflet.js with OpenStreetMap tiles displaying farmer pins, aggregation hub markers, and multi-stop delivery routes.
- **Complete Bilingual Localization (English & हिन्दी):** Fully translated UI with instant navbar switcher, session persistence, Noto Sans Devanagari typography, dynamic Leaflet & Chart.js localization, and invariant ₹ currency and kg/km metrics.
- **Automated Test Suite:** 45 end-to-end and unit tests executing in an automated testing harness with 100% pass rate.

### Illustrative / Demonstration Prototypes
- **Fictional Geolocation Coordinates:** Farmer and collection point coordinates around Greater Noida (Dadri, Pari Chowk, Surajpur, Jewar) are realistic demonstration coordinates; no live GPS tracking hardware is integrated.
- **Straight-Line Distance Metric:** Distances use spherical Haversine formulas. An external road-routing API (e.g., OSRM, GraphHopper) is not required for local execution; straight-line distance is explicitly labeled as an approximation.
- **AI Price Guidance:** Operates in labeled Demonstration Mode with regional seasonal heuristics until real AGMARKNET CSV data is imported and trained via the included CLI tool.
- **Financial Transactions:** Order requests, shared trip allocations, and group pools reflect estimated cost shares; no external payment gateway (e.g., Razorpay/UPI) or escrow service is connected.

---

## 12. Current Limitations & Future Roadmap

### Current Limitations
1. **External Routing Engine:** Relies on straight-line distance calculations rather than real-time turn-by-turn road networks.
2. **Payment Gateway Integration:** Payment settlements and escrow deposits are not automated.
3. **Live Geolocation Tracking:** Delivery vehicles do not stream live telemetry or telemetry pings.
4. **Notification Infrastructure:** Alerts and order updates are in-app; SMS (e.g., Twilio) or WhatsApp notifications are not integrated.

### Future Roadmap
1. **OSRM / OpenRouteService Integration:** Fetch exact road kilometers and transit duration matrices.
2. **UPI / Escrow Smart Contracts:** Direct peer-to-peer farmer settlement upon digital delivery signature.
3. **Multi-Farm Cart:** Allow buyers to assemble a basket across multiple local producers with unified logistics.
4. **Vernacular Voice Interface:** Hindi and regional language voice search (speech-to-text) for hands-free farmer interaction (bilingual text interface completed).

---

## 13. Production Deployment on Vercel

AgriLink AI is configured for seamless deployment to Vercel Serverless Functions using the native Python runtime.

### 13.1 Vercel Deployment Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Vercel Edge Global CDN                             │
│  ├─ /static/*  ──> Cached & served directly from public/static/             │
│  └─ /*         ──> Rewritten by vercel.json to Serverless Python Function   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                  Vercel Serverless Function (api/index.py)                  │
│                     Python 3.14 + Flask Application                         │
│  • Session Security: Signed cookies (Secure=True, SameSite=Lax, HttpOnly)   │
│  • Stateless / Ephemeral Container: No writable local persistent disk        │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ DATABASE_URL / POSTGRES_URL
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                    Managed PostgreSQL Database (Production)                 │
│              (Neon / Supabase / Vercel Postgres / Render)                   │
│  • Persistent relational storage across all cold starts and serverless instances│
│  • Idempotent DDL schema initialization & atomic transactions               │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 13.2 Ephemeral Storage vs Managed Database Strategy

> **CRITICAL ARCHITECTURAL REQUIREMENT:**  
> Vercel functions execute in ephemeral, serverless containers where the local filesystem outside `/tmp` is strictly read-only.
> Any data written to local SQLite files in `/tmp` is destroyed when serverless instances spin down or spin up concurrently.
> 
> - **Local Development:** Uses built-in SQLite (`instance/agrilink.db`).
> - **Vercel Production:** Requires an external managed **PostgreSQL** database (e.g., [Neon](https://neon.tech), [Supabase](https://supabase.com), or Vercel Postgres).
> - Setting `DATABASE_URL` or `POSTGRES_URL` automatically activates PostgreSQL mode with atomic transactions and persistent storage.

### 13.3 Environment Variables Reference

Configure these in the Vercel Dashboard under **Project Settings → Environment Variables**:

| Variable | Description | Required? | Example Value |
|---|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string from managed provider | **Yes** (for persistent DB) | `postgresql://user:pass@ep-cool.us-east-1.neon.tech/agrilink?sslmode=require` |
| `AGRILINK_SECRET_KEY` | Flask session cryptographic signing key | **Yes** (in production) | Generate via `python -c "import secrets; print(secrets.token_hex(32))"` |
| `AGRILINK_HTTPS` | Enforces HTTPS secure cookies | Optional (defaults to `1` on Vercel) | `1` |
| `AUTO_SEED` | Seeds demonstration farmers, listings & hubs on first boot | Optional (default: `1`) | `1` (initial deploy), `0` (after seeding) |

### 13.4 Step-by-Step GitHub & Vercel Deployment

#### Step 1: Provision a Free PostgreSQL Database
1. Create a free PostgreSQL instance at [Neon](https://neon.tech) or [Supabase](https://supabase.com).
2. Copy the Connection String URI (e.g., `postgresql://...`).

#### Step 2: Push Repository to GitHub
```powershell
git init
git add .
git commit -m "Configure AgriLink AI for Vercel deployment with PostgreSQL support"
git branch -M main
git remote add origin https://github.com/your-username/agrilink-ai.git
git push -u origin main
```

#### Step 3: Import into Vercel
1. Go to [vercel.com](https://vercel.com) and log in.
2. Click **Add New… → Project**.
3. Import your `agrilink-ai` GitHub repository.
4. Framework Preset: Leave as **Other** (Vercel automatically detects `vercel.json` and `api/index.py`).
5. Open **Environment Variables** and add:
   - `DATABASE_URL` = `<your-postgresql-connection-uri>`
   - `AGRILINK_SECRET_KEY` = `<your-32-byte-hex-secret>`
   - `AUTO_SEED` = `1`
6. Click **Deploy**.

#### Step 4: Verify Deployment
Once build succeeds, your public URL (`https://<project-name>.vercel.app`) is live!
- The landing page loads with CSS, SVG illustrations, and English/हिन्दी language selector.
- The database tables are automatically initialized and seeded with demo accounts (`farmer1@demo.agrilink.test` … `buyer3@demo.agrilink.test`, password `Demo@1234`).
- All marketplace listings, price estimations, shared trips, and route planner maps operate with full persistent storage.

