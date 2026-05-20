# Conceptual Data Model

This document outlines the core domain model for our genealogical database. It focuses entirely on historical realities, entities, and relationships, remaining strictly independent of implementation details or storage formats.

## Core Entities

### 1. Persona (Individual Evidence)
A distinct individual as described or implied within a single specific historical record source. A Persona represents a historical "assertion" of a person rather than a consolidated conclusion.
* **Attributes:** Implicit name variants, estimated age or dates based strictly on the record.

### 2. Consolidated Person
A single historical individual synthesized by linking multiple Personas across different records.
* **Attributes:** Evaluated identity, cross-referenced lifespans, and direct links to the constituent Personas that justify the consolidation.

### 3. Source Record
The container for historical evidence (e.g., a line in a parish register, a land lease entry). All Personas, Events, and Facts are derived directly from a Source Record.

### 4. Event
A historical occurrence with a specific time and place involving one or more Personas (e.g., a baptism, marriage, burial, or land lease signing).
* **Attributes:** Date/Date range, Location, Event Type.

### 5. Fact
An asserted attribute or characteristic belonging to a Persona or an Event (e.g., occupation, residence, religion, status).

---

## Core Relationships

* **Source Record ──> Event:** A Source Record documents one or many Events.
* **Event ──> Persona:** An Event connects one or more Personas in specific roles (e.g., principal, witness, father, sponsor).
* **Persona ──> Fact:** A Persona possesses specific Facts established by the record.
* **Persona ──> Persona (Relational):** Direct immediate relationships mentioned explicitly in a record (e.g., "wife of", "son of").
* **Consolidated Person ──═ <Collection of Personas>:** A one-to-many grouping mapping an established real-world identity to all its independent record-based mentions.
