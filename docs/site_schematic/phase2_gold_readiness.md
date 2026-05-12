# Site Schematic Golden Baseline and Repo Gap Audit

## Purpose

This document turns the two uploaded packets into the **golden acceptance baseline** for the two main site-schematic routes you want to support:

1. **Wireless / AP-heavy telecom packet** — `100643PLANSD-4.pdf`
2. **Low-voltage / structured cabling + security + MATV packet** — `2026-01-19 CONSOLIDATED SET - SOUTHERN POST - T (1) (1) (1).pdf`

It also audits the merged repo zip to show how close the implementation is to the target architecture and what old CAD-lane pieces can or cannot be removed yet.

---

## The two routes these packets represent

### Route A — Wireless / telecom / AP-heavy packet
Use this route as the canonical golden for:
- university / campus telecom sheets
- access point heavy layouts
- large symbol-sheet + abbreviation-sheet first pages
- part-plan floor sheets with AP / CM / WM / AV / CIP / CSP / RS markers
- telecom risers with MDF / IDF / OSP fiber / copper / grounding
- installation/detail pages where outlet semantics and rack/bonding details are explicit

### Route B — Low-voltage / hotel structured cabling + security + MATV packet
Use this route as the canonical golden for:
- hospitality low-voltage packets
- structured cabling + security + access control + intercom + CCTV + MATV in one set
- requirements/spec pages with a drawing index and long note columns
- symbol legend tables with per-device cable / termination / mounting / rough-in / power rules
- equipment-room layouts, conduit risers, cabling risers, MATV risers, rack details, security details, installation details
- packets where meaning is distributed across notes, legends, keyed notes, room layouts, and risers instead of only plan symbols

---

## Universal extraction contract across both routes

Any universal site-schematic system should extract the following, regardless of project:

### Packet-level
- packet id
- page count
- typed page count
- overlay profile: wireless / low_voltage / mixed
- sheet inventory
- sheet order
- drawing index rows
- project identity and issue metadata
- packet-wide standards / warranty / testing / coordination / review requirements

### Page-level
- page index
- sheet number
- sheet title
- sheet type
- overlay tags
- typed regions with bbox + provenance:
  - title_block
  - revision_block
  - legend_block
  - abbreviation_block
  - notes_spec_block
  - schedule_table_block
  - plan_body_block
  - detail_block
  - border_noise_block

### Legend / glossary layer
- symbol legend entries
- abbreviation entries
- outlet type definitions
- mounting rules
- termination rules
- conduit rough-in rules
- power requirements
- cable counts and cable types
- color conventions
- tag semantics
- keyed note semantics

### Plan-body layer
- room labels
- closet / MDF / IDF / TR labels
- equipment room labels
- plan symbol instances
- note callouts and keyed note references
- routing notes (run to / homerun to / nearest IDF / from MDF below to IDF above)
- mount type hints (CM / WM / EXT / above ceiling / behind access panel / AFF)
- service loop / slack requirements
- special environment notes (clean room, exterior weatherproof, elevator, fire alarm, POS, guestroom)

### Riser / detail layer
- vertical topology
- inter-floor transitions
- backbone media types
- conduit counts / sleeve counts / pull boxes / weatherheads / meet-me boxes
- rack / tray / ladder rack / wire management / 110 block / patch panel details
- grounding details
- CCTV schematic / security detail / installation detail / typical outlet detail / J-hook detail / bonding detail

### Graph layer
Nodes:
- Packet
- Sheet
- Region
- LegendEntry
- AbbreviationEntry
- DrawingIndexRow
- NoteClause
- Room
- Closet
- EquipmentRoom
- DeviceInstance
- OutletType
- OutletInstance
- CableRun
- Conduit
- PullBox
- RiserEdge
- Rack
- PatchPanel
- Busbar
- GroundConductor
- Constraint
- ResponsibilityAssignment
- TestingRequirement
- LabelingRequirement
- EnvironmentalRequirement

Edges:
- appears_on_sheet
- contains
- defined_by
- defined_on_page
- located_in
- located_in_region
- routes_to
- homeruns_to
- terminates_at
- matches_legend
- related_note
- constrained_by
- grounded_by
- requires
- sourced_from
- transitions_to_floor
- serves_room

### Legality / uncertainty layer
Every extracted fact should carry one of:
- stated
- inferred
- approximate
- coordination_required
- field_verify_required
- owner_furnished
- vendor_specific
- weakly_linked
- unresolved
- conflicting

---

## Golden baseline — Route A: Wireless / AP-heavy telecom packet

## Packet summary
- File: `100643PLANSD-4.pdf`
- Page count: 32
- Typed pages: 32
- Sheet type counts from smoke run:
  - `legend_symbol`: 1
  - `floorplan_overall`: 27
  - `equipment_room_layout`: 1
  - `rack_detail`: 1
  - `riser_diagram`: 1
  - `installation_detail`: 1
- Legend entries found in smoke run: 105
- Abbreviations found: 72
- Symbol instances found: 696
- Linked symbol instances: 233
- Graph nodes / edges: 3813 / 5173

## Golden page inventory
- `TC001` — TELECOMM SYMBOL LIST
- `TC100` — LOWER LEVEL PLAN OVERALL
- `TC100.2` through `TC104.5` — part plans / floor plans
- `TC200` / `TC201` — telecom part plans
- `TC301` — TELECOMM RISER DIAGRAM
- `TC502` — TELECOMM DETAILS

## What must be perfectly extracted from page 1 (`TC001`)

### Regioning
Page 1 must be zoned into at least:
- legend block
- abbreviation block
- outlet type description block
- general notes block
- horizontal cabling notes block
- junction box and conduit notes block
- drawing list block
- title / revision block

### Core text facts on page 1
The parser should extract these as **stated facts**, not vague summaries:
- pull box required when bends exceed 180° and/or 100' in length
- conduit bend radius for telecom conduits = 10 to 15 times conduit diameter
- junction boxes for telecom cabling require tamper proof screws
- include all required junction and pull boxes even if omitted graphically
- size pull/junction boxes per field conditions and ANSI/EIA/TIA-569A guidelines
- all empty conduits need at least two nylon drag cords and bushed ends
- pull boxes and junction boxes provided by electrical contractor
- provide 1 1/4" conduit from each telecom outlet to nearest accessible ceiling or cable tray
- provide double-gang back box with single-gang reducer bracket for each telecom outlet
- **for each WAP provide 2-port surface mounted biscuit box**
- all cables labeled at both ends 6" from termination
- provide 12" slack for each telecom cable at workstation end
- **provide 20' slack for wireless access points**
- **terminate WAP cables on dedicated patch panel**
- all voice and data horizontal cables plenum rated
- wallphone outlet mounting 54" AFF
- AP outlet is standard ceiling-mounted telecom 2-data outlet with two CAT6A jacks
- voice horizontal cables for certain use cases terminate on separate patch panels from data cables
- dedicated patch panel separation between data and phone patches
- one quad receptacle and two L6-20 receptacles for each equipment rack/cabinet (provided by EC)
- direct-attach RJ45 plug at room scheduler end where noted

### Color and outlet conventions that must be emitted structurally
- all data cables blue unless noted otherwise
- workstation / patch panel jack colors:
  - red = wireless
  - green = cameras
  - black = wall phones / elevators
  - blue = LAN
- AV = two CAT6A jacks
- RS1 / RS2 / RS3 = room scheduling panel outlets

### Symbol / abbreviation contract from page 1
The parser should produce normalized legend/abbreviation entries for at least:
- AP
- WM
- CM
- EXT
- AV
- RS1 / RS2 / RS3
- CIP
- CSP2 / CSP3
- PB / pull box / junction box
- conduit turned up / down
- sleeve through wall / conduit through wall
- telecom outlet identification tag
- detail / revision / elevation tag symbols
- abbreviations such as MDF, IDF, CCTV, TV, TELCO, UTP, AFF, JBOX, HVAC, PBX, CATV, NEC, etc.

### Drawing list on page 1
The drawing list itself is gold. It should populate sheet inventory and expected sheet-type priors.

## What must be perfectly extracted from plan sheets

### Symbol instance vocabulary
These are the recurring visual/text tokens that should be detected as symbol instances or keyed plan markers:
- AP
- CM
- WM
- EXT
- AV
- RS1 / RS2 / RS3
- CIP
- CSP2 / CSP3
- PP
- FIC
- TV
- POS-T / POS-P
- WN / ZN where present
- numeric port counts (1 / 2 / 3 / 4 / 5 / 6)

### Plan-body facts that matter universally
The parser should capture:
- room labels
- closet labels such as `0TC1`, `1TC2`, etc.
- run-to / homerun rules from plan notes
- AP instance location per room/zone/part-plan
- wall-mount vs ceiling-mount vs exterior AP context
- AV and scheduler outlet context
- part-plan matchlines and their continuity semantics
- exceptions like stainless steel faceplates for clean rooms

### Explicit route-specific notes from floor plans
Examples that should be recoverable:
- lower-level part plans run all tel/data devices on that floor to `0TC1`
- first-floor part 1 runs devices right of a given column line to `1TC2`
- many pages say “run all tel/data devices on this floor to nearest tele data closet”
- clean room note requires stainless steel faceplates for certain tel/data locations
- exterior WAP note: if WAPs cannot mount to structure, place within planters, provide 3/4" conduit to planters, use weatherproof enclosure

## What must be perfectly extracted from the riser page (`TC301`)
Page 31 is one of the most important gold pages in the whole packet.

The parser should recover:
- grounding bar detail / insulated ground bar / wall mounting bracket objects
- floor stack labels: lower level, 1st floor, 2nd floor, 3rd floor, 4th floor, penthouse, roof
- room hierarchy: MDF plus east/west IDFs
- riser summary facts:
  - 25-pair CAT5e copper cable from MDF to each IDF
  - 12-strand singlemode armored fiber from MDF to each IDF
  - OSP 48-strand singlemode outdoor armored fiber between buildings
  - LC connector termination for fiber and loaded fiber panels at both ends
  - 50-pair CAT3 OSP copper terminated on 110 blocks
  - 100-pair building entrance protection blocks on both ends
  - 25-pair CAT5e terminated on 24-port angled patch panels
- riser notes:
  - voice and data risers in separate sleeves
  - label conduits by intended usage
  - provide fireproofing for conduits and sleeves
  - existing TR spaces remain operational during construction
  - pull box rules for >180° bend or >100 feet
  - each conduit/sleeve has bushed ends and at least one pull string
- grounding notes:
  - all telecom grounding wire in separate 1" conduit
  - all tel/data rooms tied back to MDF with #6 AWG ground or main electrical ground
  - TGB / TMGB / TBB / GE terminology and sizing table

## What must be perfectly extracted from the detail page (`TC502` / page 32)
The parser should recover detail semantics, not just sheet type:
- standard floor-mounted data outlet detail
- standard ceiling-mounted AP outlet detail
- wall-mounted voice/data outlet detail
- wall phone outlet detail
- typical riser cable support detail
- bonding detail
- J-hook detail
- ladder rack detail
- typical riser sleeve detail
- T568B jack pin/pair assignment detail
- outlet ID label conventions
- AP biscuit box composition
- ladder rack and equipment rack relationships
- bonding notes:
  - each rack bonded to grounding busbar with #4 AWG insulated ground wire
  - do not daisy-chain racks
  - bond all ladder rack / cable tray joints and bond to ground busbar with #4 AWG insulated ground wire
  - do not bond ladder rack or cable tray to equipment racks

## Golden graph expectations for Route A
At minimum, the graph should support these exact patterns:
- `AP instance -> matches_legend -> AP legend entry`
- `AP instance -> room_context -> room label`
- `AP instance -> related_note -> 20' slack / dedicated patch panel`
- `AP instance -> related_note -> owner-provided bracket/WAP`
- `CCTV-related instance -> related_note -> dedicated WAP/CCTV patch panel`
- `room/page -> routes_to -> nearest closet or named closet`
- `IDF/MDF nodes -> topology edges -> riser connections`
- `rack/ladder/busbar detail objects -> grounded_by/bonded_to`

## Golden acceptance criteria for Route A
A packet like this is “gold” only if the parser can produce:
- page 1 legend + abbreviation + note extraction almost losslessly
- AP/CM/WM/EXT/AV/CIP/CSP/RS plan-token detection on floor sheets
- room/closet routing notes from plan sheets
- riser topology and grounding extraction from `TC301`
- outlet / rack / bonding detail extraction from `TC502`
- explicit unresolved states where a token is found but not confidently legend-linked

---

## Golden baseline — Route B: Low-voltage / structured cabling + security + MATV packet

## Packet summary
- File: `2026-01-19 CONSOLIDATED SET - SOUTHERN POST - T (1) (1) (1).pdf`
- Page count: 18
- Typed pages: 18
- Sheet type counts from smoke run:
  - `notes_spec`: 1
  - `legend_symbol`: 1
  - `schedule_sheet`: 1
  - `floorplan_overall`: 7
  - `floorplan_detail`: 1
  - `equipment_room_layout`: 1
  - `riser_diagram`: 3
  - `rack_detail`: 1
  - `installation_detail`: 2
- Legend entries found in smoke run: 76
- Abbreviations found: 9
- Symbol instances found: 143
- Linked symbol instances: 56
- Graph nodes / edges: 896 / 1164

## Golden page inventory
- `T000` — PROJECT REQUIREMENTS NOTES & SPECS
- `T001` — SYMBOLS & LEGENDS
- `T002` — SCHEDULES & MISCELLANEOUS
- `T100` — PARKING LEVEL FLOOR PLAN
- `T101` — LOBBY LEVEL FLOOR PLAN
- `T102` — 2ND LEVEL FLOOR PLAN
- `T103` — 3RD LEVEL FLOOR PLAN
- `T104` — 4TH LEVEL FLOOR PLAN
- `T105` — 5TH LEVEL FLOOR PLAN
- `T106` — ROOF PLAN
- `T700` — ENLARGED GUESTROOM LAYOUTS
- `T900` — ENLARGED EQUIPMENT ROOM LAYOUTS
- `T901` — CONDUIT RISER DIAGRAM
- `T902` — CABLING RISER DIAGRAM
- `T903` — MATV CABLING RISER DIAGRAM
- `T904` — EQUIPMENT RACK DETAILS
- `T905` — SECURITY INSTALLATION DETAILS
- `T906` — INSTALLATION DETAILS

## What must be perfectly extracted from page 1 (`T000`)

### Regioning
Page 1 should zone into multiple long-form note/spec blocks plus a drawing index block.

### High-value project requirements / universal constraints
This page is the low-voltage route’s control center. The parser should recover, at minimum:
- security system includes CCTV, digital recorder(s), duress alarms, door contacts, intercom units
- contractor provides complete system components/cabling/hardware/training
- labeling follows EIA/TIA 606A / 568C style guidance
- no hand-written labels
- structured cabling warranty = 15 years
- all other systems warranty minimum = 1 year
- certification in CAT-6 required for data/voice portion
- firestopping obligations and rated wall/floor penetration rules
- guestroom level cables routed to appropriate IDF per riser diagram
- horizontal fiber = 50/125 multimode where applicable
- SC connectors unless otherwise noted
- multimode visible portion aqua, singlemode visible portion yellow
- field verification of cabling pathways is contractor responsibility
- all MDF, IDF and AV rooms maintain 70°F and less than 60% RH
- MATV outlet homeruns and MATV MDF/IDF backbone via RG-11 / hardline
- no coring or floor drilling without GC approval
- infrastructure scope includes voice, data, MATV, CCTV, intrusion detection
- standards list: TIA 568 / 569 / 606 / 607 and related NEC/NFPA/local code references
- pull box every 100' of straight run or every two 90° bends
- pull string in all conduits
- outlet conduits stubbed to accessible ceiling contiguous to destination room
- conduits marked for data/voice, TV, or security use only
- conduits EMT unless otherwise noted
- grounding notes:
  - TGB 2"x12" busbar in IDF
  - TMGB 4"x12" busbar in MDF
  - install busbar minimum 18" AFF with 6" clearance on all sides
  - minimum #6 AWG green grounding conductor to each rack and bonded ladder rack
- training requirements
- unit pricing requirements
- Wi-Fi design note: vendor designs Wi-Fi, performs site survey before ceiling closure, reports needed WAP revisions, coordinates with GC
- drawing index rows for all 18 sheets
- as-built requirements and test/certification requirements

### Universal implication
A parser that misses page 1 on this packet is not a low-voltage parser yet.

## What must be perfectly extracted from page 2 (`T001`)
This is the second critical gold page.

### Structured cabling symbol legend / outlet definitions
The parser should recover structured outlet types such as:
- `# PORT DATA OUTLET`
- `# PORT DATA FLOOR BOX OUTLET`
- `# PORT ADMIN OUTLET`
- admin floor box outlet
- point-of-sale terminal outlet
- point-of-sale printer outlet
- data + fiber outlet
- timeclock outlet
- digital signage outlet
- wall-mounted wireless node outlet
- ceiling-mounted wireless node outlet
- ceiling-mounted Zigbee node outlet
- ceiling-mounted generic outlet
- guestroom desk data outlet
- bed phone outlet (VoIP)
- house phone outlet (VoIP)
- data/voice combination outlet
- phone outlets (analog)
- fire alarm control panel voice outlet
- IPTV data TV outlet
- coax TV outlet
- coax + data outlet
- coax + data + fiber outlet
- J-hook pathway

For each outlet type, gold extraction should include:
- cable count
- cable description
- work-area termination
- closet termination
- standard mounting height AFF or above-ceiling
- electrical rough-in
- power requirement
- remarks / special coordination / service loop / vendor specificity

### Security / access / CCTV legends
The parser should also recover and normalize:
- door contact
- duress alarm push button
- motion detector ceiling mounted
- keypad
- security control panel
- card reader
- intercom remote station
- intercom remote station at vestibule/loading dock
- elevator remote access reader
- telephone entry system station
- proximity reader
- single-button emergency phone station
- mini dome single lens camera ceiling mounted
- mini dome single lens camera wall mounted
- fixed bullet style camera wall mounted
- mini dome 180° camera ceiling mounted
- mini dome 360° camera ceiling mounted
- custom camera symbolic form

### Legend-note layer
The parser should retain legend notes such as:
- some items may not be included in this project
- rough-in requirements are reference information only
- final product cut sheets required in submittals
- exterior components need weatherproof rated enclosures
- card readers on floor plans are for visual reference only; final locations come from door hardware schedule
- all cross connecting of station voice cables to riser cables is in scope
- all amps and taps for TV distribution are in scope

## What must be perfectly extracted from page 3 (`T002`)
This page includes schedules / specs / miscellaneous content.
Gold extraction should capture:
- copper component specs list
- manufacturer + part number + comments for major components
- cable jacket colors and part numbers
- data jack / faceplate / block / patch panel / rack component schedules
- any direct mapping from component schedule to legend entries or detail sheets

## What must be perfectly extracted from floor plans (`T100`–`T106`, `T700`)

### Visual marker vocabulary
This route includes a richer plan-body marker vocabulary than the wireless packet. The parser should support at least:
- WN
- ZN
- TV
- POS-T
- POS-P
- 180°
- 360°
- AP-like / node-like / camera-like markers
- MD / H / WP / AFF-like annotations where present
- keyed note numbers
- cable zoning notes
- homerun notes
- references to T900 / T906 details

### Typical plan-body facts to recover
- room labels, including public spaces, guestrooms, support spaces, closets
- explicit MDF / IDF room labels
- keyed notes tied to devices and rooms
- routing notes such as “homerun all cables on this level to MDF room / IDF-2 / IDF-4”
- wireless node notes such as:
  - 15'-0" service loop
  - within reach of accessible ceiling space or behind access panel
  - surface mounted
- Zigbee hub access point notes:
  - mount above ceiling
  - located next to access panel
  - deduct alternate / exact mount coordination
- key card access system is coordination-only / derive final from door hardware schedule
- POS terminals and POS printers requiring monitoring / dedicated outlet treatment
- “install cable only, provide 25' service loop” when called out
- roof satellite dish note with weatherhead and pull string

## What must be perfectly extracted from `T900` equipment room layouts
The parser should recover the equipment-room sheet as a composite detail sheet containing:
- MDF/Data room layout
- MATV backboard elevation
- 110 block elevation
- chase backboard elevation
- front view MDF rack elevation
- telecommunications grounding riser diagram
- front view MDF rack interconnectivity
- IDF-2 layout
- IDF-4 layout

This page should populate room-level graph nodes for:
- MDF/Data room
- IDF-2
- IDF-4
- rack groups
- backboards
- 110 block fields
- grounding diagram
- interconnectivity relationships

## What must be perfectly extracted from `T901` conduit riser
The parser should recover:
- conduit notes: no more than two 90° bends / 180° aggregate without pull box
- all conduit stubs reamed and bushed
- all conduits contain pull string
- all conduits routed overhead except incoming service/demarc cases
- label conduit ends with destination
- below-grade conduit material rules
- service-provider meet-me box at property line
- 4" sleeves / 4" conduits / 24"x24"x8" pull box / weatherhead for satellite feeds
- MDF/Data room, IDF-2 chase, IDF-4 vertical relationships
- guestroom raceway keyed notes
- WAP patch-cord-through-TV-outlet note if shown in raceway notes

## What must be perfectly extracted from `T902` cabling riser
The parser should recover:
- legend items `PP`, `FIC`, `110 blocks`
- 12-count multimode fiber optic cable to each IDF
- three 4-pair CAT-6 cables to each IDF
- patch-to-punch cross-connect semantics
- elevator control room feeds from roof where indicated
- vertical topology: MDF/Data room -> IDF-2 -> IDF-4 and any floor transitions

## What must be perfectly extracted from `T903` MATV riser
The parser should recover:
- MATV legend and distribution components
- satellite dish node
- weatherhead for satellite feeds
- 24"x24"x8" pull box
- seven RG-11 feeds
- outdoor rated cable
- 10' slack for termination by MATV vendor
- public area TV branch note
- MATV cable ownership/provider distinctions

## What must be perfectly extracted from `T904` rack details
This page is critical for structured cabling buildout rules. Gold extraction should include:
- patch panels are 48-port density, 2U
- install sufficient quantity/port configuration for incoming horizontal data and telephone patch system cables
- admin outlet data cables terminate on dedicated patch panels
- equipment racks supported overhead with 18" x 6" cable tray from racks to wall
- ladder rack allowed in IDF rooms with ceilings under 8'-0"
- minimum 18" clearance rules where stated
- vertical wire management part/model callouts
- horizontal wire management 2 RU (3.5")
- all IDF/MDF cross-connect fields use 110 blocks
- D-rings not permitted in 110 field
- UPS minimum 15 minutes for IT equipment in IDF/MDF rooms
- all racks/hardware grounded per TIA/EIA & NEC; racks have vertical ground strips

## What must be perfectly extracted from `T905` security installation details
Gold extraction should include:
- intrusion detection system contractor scope
- CCTV installation requirements
- shop drawings before installation/purchase
- alternate products possible with cut sheets required
- installer provides complete CCTV system: cabling, transceivers, patch panels, switches, cameras, recorders, storage, VMS software
- CCTV network must be separate and dedicated
- edge/core switches powered by UPS
- cameras record on motion with minimum frame rate / resolution / storage retention rules
- CCTV system components schedule
- CCTV schematic design
- CCTV camera detail

## What must be perfectly extracted from `T906` installation details
Gold extraction should include detail-level semantics for:
- above-ceiling outlet / access hatch / service loop details
- ground wire and busbar details
- outlet detail families such as POS-P, POS-T, TV, admin outlet, wireless node / Zigbee node outlet
- “category cable home run to IDF” detail note
- desk outlet / guestroom switch plug details
- keyed symbol-to-detail mappings used by plan sheets

## Golden graph expectations for Route B
At minimum, the graph should support these patterns:
- `wireless node instance -> matches_legend -> wall or ceiling wireless node outlet`
- `wireless node instance -> related_note -> service loop / surface mount / access panel`
- `zigbee node instance -> matches_legend -> Zigbee node outlet`
- `POS instance -> matches_legend -> dedicated POS patch panel`
- `admin outlet -> terminates_at -> dedicated admin patch panel`
- `room / floor -> homeruns_to -> MDF / IDF-X`
- `TGB/TMGB/#6 AWG/rack -> grounded_by`
- `satellite dish -> related_note -> weatherhead / pull string / roof approval`
- `camera instance -> matches_legend -> CCTV symbol entry -> related_note -> dedicated CCTV network`
- `card reader / intercom / duress / motion -> matches_legend -> device-specific rough-in / cable / power rules`

## Golden acceptance criteria for Route B
A packet like this is “gold” only if the parser can produce:
- lossless page-1 requirements extraction
- lossless page-2 symbol-table extraction across structured cabling + security + access + CCTV
- plan keyed notes and routing notes on all floor sheets
- equipment-room layout extraction for T900
- riser topology extraction for T901/T902/T903
- rack/security/installation detail extraction for T904/T905/T906
- wiring color conventions including blue / gray / yellow distinctions
- unresolved states where plan symbol is present but not confidently legend-grounded

---

## Universal visual primitives both routes prove you need

Do **not** train final semantics first. These packets prove the primitive detector should focus on:
- AP-like marker
- camera-like marker
- outlet glyph
- port-count annotation
- tag bubble / keyed note tag
- card-reader-like symbol
- intercom / phone station symbol
- rack / cabinet / patch-panel-like shape
- pull-box / conduit / sleeve / weatherhead icon
- riser arrow / vertical stack / floor transition marker
- label token clusters such as AP / CM / WM / EXT / POS-T / POS-P / WN / ZN / TV / PP / FIC

Then map local meaning through legends and notes.

---

## Repo audit from the merged zip

## What is already in good shape
From the merged zip audit, the repo already has the **right structural lane** for Phase 2:
- `src/orbitbrief_core/parser/site_schematic/`
- `classification/`
- `zoning/`
- `legends/`
- `symbols/`
- `graph/`
- `overlays/`
- `projection/`
- `config/`
- `extractors/`
- `config/runtime/site_schematic_models.yaml`
- site-schematic tests and smoke tests

The smoke results also show the current implementation is already producing typed pages, legend entries, symbol instances, linked symbol instances, and graph outputs on both packets.

## What is structurally working now
- sheet classification exists
- page zoning exists
- legend / abbreviation / outlet-type parsing exists
- heuristic primitive symbol detection exists
- heuristic symbol linker exists
- packet graph builder exists
- site_schematic adapters exist
- model registry config exists
- overlay handling for wireless and low_voltage exists

## What is still missing before the architecture is “final-stage”
The merged repo is **not** yet at the full desired end-state. The main gaps are:

### 1. Site_schematic still rides on CAD wrappers
`site_schematic_pdf.py` subclasses `CadPdfAdapter`, and `site_schematic_image.py` subclasses `CadImageAdapter`.
That means site_schematic is not yet fully decoupled.

### 2. Runtime spine still speaks CAD more than site_schematic
The runtime still routes drawing packets through `runtime_spine/extractors/cad_packet_to_claims.py` and broader `drawing_packet` semantics.
That is a major sign that the rename is not complete yet.

### 3. The graph is still thinner than the target graph
Current graph edges mostly cover:
- page contains region
- page defines legend / abbreviation
- page contains symbol
- symbol matches legend
- symbol related_note
- symbol room_context

It does **not** yet look like the richer target graph where routing, termination, grounding, topology segments, legality, and explicit unresolved/conflicting semantics are first-class edge types everywhere.

### 4. Detector and verifier are still scaffolds
The model registry is there, but the symbol detector is still heuristic/token-driven and the verifier is not yet a bounded model-backed ambiguity resolver.

### 5. No separate legality module in site_schematic graph layer
The target architecture called for legality / stated-vs-inferred separation as a first-class concept. That is not yet a dedicated site_schematic graph module.

## How far the repo is from the desired golden
Qualitatively:
- **close on architecture**
- **good on control-sheet extraction**
- **good on regioning / legending / note parsing**
- **promising on symbol linking**
- **not yet final on graph semantics and runtime cutover**

In plain terms: the repo is already a **real Phase 2 system**, but not yet the **fully universal site-schematic system** these two gold packets imply.

---

## CAD-lane cleanup guidance

## Safe to remove now
These are cleanup items, not architectural risk:
- all `__pycache__/`
- all `*.pyc`
- `.pytest_cache/`
- `.DS_Store`
- packaged `.git/` metadata inside the shipped zip
- stale half-phase artifacts if superseded:
  - `README_SITE_SCHEMATIC_PHASE2_HALF.md`
  - `site_schematic_phase2_half_smoke_results.md`
  - any tests/docs named `phase2_half` once replacements are in place

## Do **not** remove yet
These still appear load-bearing for the current repo state:
- `src/orbitbrief_core/parser/adapters/cad_pdf.py`
- `src/orbitbrief_core/parser/adapters/cad_image.py`
- `src/orbitbrief_core/parser/adapters/cad_common.py`
- `src/orbitbrief_core/runtime_spine/extractors/cad_packet_to_claims.py`
- `src/orbitbrief_core/parser/graph/cad_passes.py`
- `src/orbitbrief_core/parser/graph/cad_signals.py`
- runtime / router references to `cad_sheet`, `floorplan`, `drawing_packet`
- coverage / postprocess rules that still use CAD-family naming

## What should become wrappers next
These are the next candidates to reduce to wrappers rather than delete immediately:
- `cad_pdf.py`
- `cad_image.py`
- `cad_packet_to_claims.py`
- CAD-specific graph passes/signals for this lane

The rule is:
- **convert them to thin delegators first**
- **only delete after runtime_spine and packet families are site_schematic-native**

---

## Recommended next implementation step
Before turning on real Paddle / YOLO / Qwen inference, use this document as the gold acceptance contract and do three things:

1. Make the repo produce gold outputs for these two packets using deterministic + heuristic logic.
2. Promote the site_schematic graph to include explicit routing / termination / grounding / topology / legality edges.
3. Only then wire in models and measure lift against this gold baseline.

---

## Most important bottom line
These two packets prove the universal system is:
- **primitive detector**
- **per-packet legend + notes grounding**
- **sheet-type extraction**
- **packet-local graph**
- **bounded verifier for ambiguity**

They do **not** justify a single global symbol detector that tries to know all project semantics directly.
