# Architecture diagrams

Five views of the same system, from the outside in. The README explains the
reasoning; this file is the picture.

GitHub renders the Mermaid below directly. The same diagrams are also committed
as PNGs in [`diagrams/`](diagrams/) for viewing offline or dropping into a slide.
To regenerate them after an edit:

```bash
npx -y @mermaid-js/mermaid-cli@11 -i docs/architecture.md -o docs/diagrams/architecture.md
```

---

## 1. Components

What the pieces are and which direction the dependencies point. Nothing above
the integrations layer names OSRM or Nominatim.

```mermaid
flowchart TD
    Client["Client<br/>Postman, curl, a map UI"]

    subgraph api["routes - the web layer"]
        View["OptimizeRouteView<br/>validate, delegate, respond"]
        Handler["exception_handler<br/>one error shape, stable codes"]
    end

    subgraph services["routes.services - the decisions"]
        Planner["trip_planner<br/>owns the call budget"]
        Projection["route_projection<br/>stations onto the route"]
        Optimizer["fuel_optimizer<br/>where to buy, how much"]
        Caching["caching<br/>the two cached calls"]
    end

    subgraph integrations["integrations - replaceable providers"]
        RoutingBase["RoutingProvider<br/>protocol"]
        GeoBase["GeocodingProvider<br/>protocol"]
        Osrm["OsrmRoutingProvider"]
        Nominatim["NominatimGeocodingProvider"]
    end

    subgraph fueldata["fuel - the dataset"]
        Finder["station_finder<br/>one bbox query"]
        Model[("FuelStation<br/>6,452 rows")]
        Gazetteer["city_coordinates<br/>offline gazetteer"]
        Importer["import_fuel_prices"]
    end

    Core["core<br/>geo maths and error types<br/>no Django, no I/O"]

    Client --> View
    View --> Planner
    View -.on failure.-> Handler
    Handler --> Client
    Planner --> Caching
    Caching --> GeoBase
    Caching --> RoutingBase
    GeoBase -.implemented by.-> Nominatim
    RoutingBase -.implemented by.-> Osrm
    Planner --> Finder
    Finder --> Model
    Planner --> Projection
    Projection --> Optimizer
    Optimizer --> View
    Importer --> Gazetteer
    Importer --> Model
    Projection --> Core
    Optimizer --> Core
    Finder --> Core
```

---

## 2. What one request costs

The whole external-call budget. Stations never trigger a network call, which is
the constraint the assignment sets.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant V as OptimizeRouteView
    participant P as trip_planner
    participant Ca as DB cache
    participant N as Nominatim
    participant O as OSRM
    participant DB as SQLite

    C->>V: POST start, finish
    V->>V: validate the body
    V->>P: plan_trip

    P->>Ca: geocode "Boston, MA"
    alt not cached
        Ca->>N: 1 HTTP call
        N-->>Ca: coordinates, country
        Ca->>Ca: store for 30 days
    end
    Ca-->>P: location
    Note over P: repeat once for the finish,<br/>then reject anything outside the USA

    alt start and finish are the same place
        P-->>V: zero route, empty plan, no routing call
    else
        P->>Ca: driving_route
        alt not cached
            Ca->>O: 1 HTTP call
            O-->>Ca: distance, duration, geometry
            Ca->>Ca: store for 7 days
        end
        Ca-->>P: route

        P->>DB: one indexed bounding-box query
        DB-->>P: candidate stations
        Note over P,DB: no network call here,<br/>however many stations match

        P->>P: project stations onto the route
        P->>P: plan the fuel
    end
    P-->>V: TripPlan
    V-->>C: 200 with route and fuel plan
```

---

## 3. Getting stations onto the route

The dataset ships no coordinates, so stations have to be placed on the map and
then placed on the route. Both steps are local.

```mermaid
flowchart LR
    CSV["fuel CSV<br/>8,151 rows<br/>no lat/lon"] --> Import["import_fuel_prices"]
    Gaz["Census gazetteer<br/>48,066 place names"] --> Import
    Import --> DB[("FuelStation<br/>6,452 rows<br/>city-centroid coords")]

    Route["route geometry<br/>from one OSRM call"] --> Box["bounding box<br/>padded by 25 miles"]
    Box --> Query["one indexed query"]
    DB --> Query
    Query --> Grid["grid index<br/>file each segment into<br/>the cells its padded box covers"]
    Grid --> Test["test a station only against<br/>the segments in its own cell"]
    Test --> Proj["ProjectedStation<br/>route_distance_miles<br/>detour_miles"]
    Proj --> Thin["thin to the cheapest<br/>station per 5 miles"]
    Thin --> Line["a line of priced points"]
```

The grid step is what makes this fast. Testing every station against every
segment is tens of millions of comparisons on a transcontinental route. Filing
each segment into the cells its corridor-padded bounding box covers, then
testing a station only against the segments in its own cell, is exact and costs
a fraction of that.

---

## 4. The fuel policy

Three rules, checked in this order. The order is the whole design.

```mermaid
flowchart TD
    Start([At the start, or at a station]) --> Q1{"Is the destination<br/>within range?"}

    Q1 -->|yes| Finish["Buy exactly the fuel to finish.<br/>Drive to the destination."]
    Finish --> Done([Done])

    Q1 -->|no| Forced["A stop is unavoidable."]
    Forced --> Pick["Rule 2<br/>Aim at the cheapest station still in range.<br/>Farthest wins ties, so fewer stops."]
    Pick --> Q2{"Is that station<br/>cheaper than here?"}

    Q2 -->|yes| Minimum["Rule 3a<br/>Buy only enough to reach it.<br/>Do not pay this price for more."]
    Q2 -->|no| Fill["Rule 3b<br/>Fill the tank.<br/>This is the cheapest fuel<br/>in the whole reachable stretch."]

    Minimum --> Q3{"Is the purchase too small<br/>to be worth pulling over,<br/>and can the tank reach anyway?"}
    Fill --> Q3
    Q3 -->|yes| Skip["Skip the purchase."]
    Q3 -->|no| Record["Record the stop."]

    Skip --> Move["Drive to that station."]
    Record --> Move
    Move --> Start
```

Rules 2 and 3 only ever move forward and only ever target a station already
within range, so the 500 mile limit holds by construction rather than by a check
after the fact.

Feasibility is settled before any of this runs. The gaps in the chain from the
start, through every candidate, to the destination are measured in one pass. A
gap wider than the range cannot be bridged however the stations are chosen, so
the request is rejected with the offending distance instead of the walk
dead-ending halfway.

```mermaid
flowchart LR
    A["start<br/>mile 0"] -->|"gap at most 500 mi?"| B["station<br/>mile 376"]
    B -->|"gap at most 500 mi?"| C["station<br/>mile 548"]
    C -->|"gap at most 500 mi?"| D["station<br/>mile 971"]
    D -->|"gap at most 500 mi?"| E["finish<br/>mile 2,794"]
    E -.->|"any gap wider<br/>than the range"| F["422<br/>NO_FEASIBLE_FUEL_PLAN"]
```

---

## 5. A real plan

New York to Los Angeles, 2,794 miles. Nine stops, every leg inside 500 miles,
279.40 gallons which is exactly the distance at 10 MPG.

```mermaid
flowchart LR
    S(["START<br/>New York NY<br/>mile 0"])
    A["Youngstown OH<br/>$3.059<br/>17.22 gal"]
    B["Toledo OH<br/>$3.009<br/>42.30 gal"]
    C["Tipton IA<br/>$2.982<br/>36.99 gal"]
    D["Waco NE<br/>$2.799<br/>50.00 gal, full tank"]
    E["Overton NE<br/>$2.899<br/>11.71 gal"]
    F["Ogallala NE<br/>$3.014<br/>12.72 gal"]
    G["Longmont CO<br/>$3.057<br/>19.94 gal"]
    H["Green River UT<br/>$3.282<br/>34.10 gal"]
    I["N Las Vegas NV<br/>$3.282<br/>16.81 gal"]
    Z(["FINISH<br/>Los Angeles CA<br/>mile 2,794"])

    S -->|376 mi| A -->|172 mi| B -->|423 mi| C -->|370 mi| D
    D -->|117 mi| E -->|127 mi| F -->|199 mi| G -->|341 mi| H
    H -->|391 mi| I -->|277 mi| Z

    D:::cheapest
    classDef cheapest fill:#d8f3dc,stroke:#2d6a4f,stroke-width:2px
```

Two things to notice. The full 50 gallon tank taken at $2.799 in Waco, Nebraska,
because nothing cheaper was in range and that was the cheapest fuel for the next
500 miles. And the small 11.71 gallon purchase in Overton immediately after,
which is rule 3a buying just enough to reach cheaper fuel rather than paying the
higher price for a full tank.
