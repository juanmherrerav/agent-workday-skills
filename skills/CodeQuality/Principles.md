# Principles.md — The CodeQuality Diagnostic Catalog (principle lens)

> The lens. Every diagnosis maps an observed **smell** → the **principle** it violates → the
> **refactoring move** that cures it. Read this before Scan part B (the design scan). Source canon:
> Robert C. Martin, _Clean Code_ & _Clean Architecture_; Martin Fowler, _Refactoring_ (smell vocabulary).

---

## Part 1 — SOLID (class/module design)

### S — Single Responsibility Principle

_A module should have one, and only one, reason to change._

| Smell                       | Signal                                            | Refactoring move                                 |
| --------------------------- | ------------------------------------------------- | ------------------------------------------------ |
| God Class / Large Class     | 1 class doing persistence + business + formatting | Extract Class; split by reason-to-change (actor) |
| Divergent Change            | one file edited for unrelated reasons             | Extract Class / Module per concern               |
| Mixed levels of abstraction | policy and detail in same method                  | Extract Method; push detail down                 |

### O — Open/Closed Principle

_Open for extension, closed for modification._

| Smell                                    | Signal                               | Refactoring move                                |
| ---------------------------------------- | ------------------------------------ | ----------------------------------------------- |
| Switch/if-else on type code              | `if type == "A" … elif "B"` repeated | Replace Conditional with Polymorphism; Strategy |
| Editing core class for every new variant | new feature = touch the same class   | Introduce abstraction + plug-in implementations |

### L — Liskov Substitution Principle

_Subtypes must be substitutable for their base types._

| Smell                   | Signal                                              | Refactoring move                                        |
| ----------------------- | --------------------------------------------------- | ------------------------------------------------------- |
| Refused Bequest         | subclass throws `NotImplemented`/overrides to no-op | Replace Inheritance with Delegation; re-model hierarchy |
| Type checks on subclass | `if isinstance(x, SubType)` before use              | Push behavior into the type; fix the abstraction        |

### I — Interface Segregation Principle

_No client should depend on methods it does not use._

| Smell                     | Signal                              | Refactoring move                            |
| ------------------------- | ----------------------------------- | ------------------------------------------- |
| Fat interface             | implementers stub half the methods  | Split interface by client (role interfaces) |
| Unused parameters/methods | clients pass nulls / ignore returns | Extract Interface; narrow the contract      |

### D — Dependency Inversion Principle

_Depend on abstractions, not concretions. High-level policy must not depend on low-level detail._

| Smell                               | Signal                                    | Refactoring move                                  |
| ----------------------------------- | ----------------------------------------- | ------------------------------------------------- |
| `new ConcreteThing()` inside policy | business logic constructs DB/HTTP clients | Inject dependency; depend on interface/protocol   |
| Hard-coded I/O in core logic        | `requests.get`, file reads in domain code | Introduce a port/adapter (seam); invert the arrow |
| Untestable unit (needs network/DB)  | can't test without infra                  | Extract interface, pass a fake in tests           |

---

## Part 2 — Clean Code (function/line level)

### Names

_A name should tell why it exists, what it does, and how it's used._

| Smell                 | Signal                                  | Move                    |
| --------------------- | --------------------------------------- | ----------------------- |
| Mysterious name       | `d`, `tmp`, `data2`, `mgr`, `process()` | Rename to reveal intent |
| Disinformation        | name lies about behavior                | Rename to match reality |
| Encodings / Hungarian | `strName`, `m_count`, `I_Foo`           | Strip noise encoding    |

### Functions

_Small. Do one thing. One level of abstraction. Few arguments._

| Smell                            | Signal                           | Move                                              |
| -------------------------------- | -------------------------------- | ------------------------------------------------- |
| Long Method                      | scroll to read it; >~20 lines    | Extract Method until each does one thing          |
| Long Parameter List              | 4+ params                        | Introduce Parameter Object; Preserve Whole Object |
| Flag Argument                    | `func(x, True)` toggles behavior | Split into two functions                          |
| Output argument / side-effect    | mutates an arg or hidden global  | Return a value; isolate the effect                |
| Nested conditionals / arrow code | deep `if` pyramids               | Guard Clauses; Replace Nested Conditional         |

### Duplication (DRY)

_Every piece of knowledge has a single, authoritative representation._

| Smell                          | Signal                  | Move                                    |
| ------------------------------ | ----------------------- | --------------------------------------- |
| Copy-paste blocks              | jscpd/dupl flags clones | Extract Method/Function; Pull Up Method |
| Parallel structures            | same shape in N places  | Extract shared abstraction / template   |
| Repeated magic numbers/strings | literals scattered      | Extract Constant; Replace Magic Number  |

### Comments & Formatting

| Smell                       | Signal                               | Move                                               |
| --------------------------- | ------------------------------------ | -------------------------------------------------- |
| Comment explaining bad code | comment compensates for unclear code | Make the code self-explanatory; delete the comment |
| Commented-out code          | dead code in comments                | Delete (version control remembers)                 |
| Dead code                   | unreachable / unused                 | Remove                                             |

### Coupling smells (Fowler)

| Smell                  | Signal                                              | Move                                            |
| ---------------------- | --------------------------------------------------- | ----------------------------------------------- |
| Feature Envy           | method uses another object's data more than its own | Move Method to the data                         |
| Data Clumps            | same group of fields travel together                | Extract Class / Parameter Object                |
| Inappropriate Intimacy | classes reach into each other's internals           | Move Method/Field; hide delegate                |
| Message Chains         | `a.b().c().d()`                                     | Hide Delegate; Extract Method                   |
| Primitive Obsession    | strings/ints model domain concepts                  | Replace Primitive with Value Object             |
| Shotgun Surgery        | one change forces edits across many files           | Consolidate into one module (Move Method/Field) |

---

## Part 3 — Severity & Leverage Scoring

Each smell in the inventory gets scored so Scan part C (the roadmap) can rank principles.

**Severity (how bad):** `1` cosmetic → `5` actively dangerous (e.g., untestable god class touched daily).

**Leverage = Impact ÷ Risk**, where:

- **Impact** ↑ with: change-frequency of the file (git churn), blast radius, how many other smells it unblocks, code volume removed.
- **Risk** ↑ with: missing tests, wide fan-in, framework/serialization coupling, public API surface.

**Heuristics:**

- Duplication and naming are usually **high impact, low risk** → do early.
- DIP/OCP on a hot, untested core class is **high impact, high risk** → needs characterization tests first; sequence after the safe wins.
- A god class nobody touches is **low leverage** → don't bother yet.

**Churn signal (any language):**

```bash
git log --since="6 months ago" --name-only --pretty=format: | sort | uniq -c | sort -rn | head -20
```

Files that are both _complex_ and _frequently changed_ are the prime targets — that's where clean code pays off fastest.

---

## Part 4 — The Refactoring Move Glossary (quick reference)

Extract Method/Function · Extract Class · Extract Interface · Inline · Rename · Move Method/Field ·
Replace Conditional with Polymorphism · Replace Type Code with Strategy/State · Introduce Parameter Object ·
Replace Primitive with Value Object · Replace Magic Number with Constant · Guard Clauses ·
Replace Inheritance with Delegation · Hide Delegate · Introduce Seam (port/adapter) · Dependency Injection.

Each move is **behavior-preserving** when done in small steps with tests green throughout.
