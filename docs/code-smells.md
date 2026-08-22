# Code Smells Reference

> **Provenance**: Condensed and paraphrased (original wording, no verbatim text) from Refactoring.Guru — index: https://refactoring.guru/refactoring/smells, entries: `https://refactoring.guru/smells/<slug>`. Crawled 2026-07-29. See source pages for full discussion and examples.
>
> **Companion**: [refactoring-techniques.md](refactoring-techniques.md). **Treatments** links resolve there, but every entry's **Fix gist** makes this file usable standalone.
>
> **How to use** — Reviewer agents: match code against **Signs**, cite the entry anchor (e.g. `code-smells.md#long-method`), quote the **Fix gist**. Planning agents: scan categories to scope cleanup; pull **Treatments** into task lists. Refactoring agents: **Fix gist** is the move; **Treatments** name the exact techniques (mechanics in the companion file).

## Contents

- [Bloaters](#bloaters) (5) — oversized methods, classes, parameter lists
- [Object-Orientation Abusers](#object-orientation-abusers) (4) — misapplied OO principles
- [Change Preventers](#change-preventers) (3) — one change forces many others
- [Dispensables](#dispensables) (6) — pointless code whose removal helps
- [Couplers](#couplers) (4) — excessive coupling between classes
- [Other Smells](#other-smells) (1)

## Bloaters

*Code, methods, and classes that have swollen to unmanageable size — usually accreted gradually rather than designed that way.*

### Long Method

- **What**: A method that has grown to dozens of lines and no longer does one thing.
- **Signs**: Hard to name concisely; internal blocks separated by blank lines or comment headers; mixed abstraction levels.
- **Why**: Adding "just one more line" is always easier than starting a new method, so logic accretes unnoticed.
- **Fix gist**: Extract each coherent block into its own well-named method; if local variables block extraction, replace temps with queries or move the whole method into a method object.
- **Treatments**: [Extract Method](refactoring-techniques.md#extract-method), [Replace Temp with Query](refactoring-techniques.md#replace-temp-with-query), [Introduce Parameter Object](refactoring-techniques.md#introduce-parameter-object), [Preserve Whole Object](refactoring-techniques.md#preserve-whole-object), [Replace Method with Method Object](refactoring-techniques.md#replace-method-with-method-object), [Decompose Conditional](refactoring-techniques.md#decompose-conditional)
- **Payoff**: Methods readable at a glance; less duplication; longer-lived code.
- **Ignore when**: A measured hot path may justify keeping code inline.

### Large Class

- **What**: A class carrying far too many fields, methods, and lines to hold a single responsibility.
- **Signs**: Field and method counts keep climbing; unrelated concerns sit side by side; only a subset of state is used by any given method.
- **Why**: Bolting a feature onto an existing class costs less effort up front than designing a new one.
- **Fix gist**: Split the class along its responsibilities — pull cohesive field-and-method groups into a new class, a subclass, or an interface, and separate UI/observer duties from domain state.
- **Treatments**: [Extract Class](refactoring-techniques.md#extract-class), [Extract Subclass](refactoring-techniques.md#extract-subclass), [Extract Interface](refactoring-techniques.md#extract-interface), [Duplicate Observed Data](refactoring-techniques.md#duplicate-observed-data)
- **Payoff**: Smaller units that fit in one's head; duplication surfaces and disappears during the split.

### Primitive Obsession

- **What**: Domain concepts modelled with raw primitives and constants instead of small purpose-built types.
- **Signs**: Currencies, ranges, phone numbers, and coordinates held as strings/numbers; type codes as int or string constants; string keys used as pseudo-field names in arrays or maps.
- **Why**: Adding one more primitive field feels cheaper than introducing a class, so the shortcut is taken repeatedly.
- **Fix gist**: Give each recurring primitive concept its own class, group co-travelling primitives into a parameter object, and turn type codes into classes, subclasses, or strategy objects.
- **Treatments**: [Replace Data Value with Object](refactoring-techniques.md#replace-data-value-with-object), [Introduce Parameter Object](refactoring-techniques.md#introduce-parameter-object), [Preserve Whole Object](refactoring-techniques.md#preserve-whole-object), [Replace Type Code with Class](refactoring-techniques.md#replace-type-code-with-class), [Replace Type Code with Subclasses](refactoring-techniques.md#replace-type-code-with-subclasses), [Replace Type Code with State-Strategy](refactoring-techniques.md#replace-type-code-with-state-strategy), [Replace Array with Object](refactoring-techniques.md#replace-array-with-object)
- **Payoff**: Behaviour lives next to the data it governs; validation happens once; duplication becomes visible.

### Long Parameter List

- **What**: A method signature taking more than three or four arguments.
- **Signs**: Call sites are unreadable walls of arguments; parameter order is easy to get wrong; the list keeps growing with each feature.
- **Why**: Several algorithms get merged into one method, or data is threaded through as parameters to avoid depending on the object that holds it.
- **Fix gist**: Let the method fetch what it can from the receiver, pass the whole object instead of picking it apart, and bundle any remaining group of arguments into a parameter object.
- **Treatments**: [Replace Parameter with Method Call](refactoring-techniques.md#replace-parameter-with-method-call), [Preserve Whole Object](refactoring-techniques.md#preserve-whole-object), [Introduce Parameter Object](refactoring-techniques.md#introduce-parameter-object)
- **Payoff**: Shorter, readable signatures; hidden duplication among callers becomes obvious.
- **Ignore when**: Shortening the list would force an unwanted dependency between classes.

### Data Clumps

- **What**: The same cluster of variables shows up together in fields and parameter lists across the codebase.
- **Signs**: Identical argument groups repeat in many signatures; deleting one member of the group leaves the rest meaningless.
- **Why**: Sloppy structure and copy-paste growth let related data spread instead of being named once.
- **Fix gist**: Promote the recurring group to its own class, then pass that object around — as a field where it belongs to the owner, as a parameter object where it only travels together.
- **Treatments**: [Extract Class](refactoring-techniques.md#extract-class), [Introduce Parameter Object](refactoring-techniques.md#introduce-parameter-object), [Preserve Whole Object](refactoring-techniques.md#preserve-whole-object)
- **Payoff**: Related operations gather in one place; the codebase shrinks and reads clearer.
- **Ignore when**: Passing the whole object would couple classes that should stay independent.

## Object-Orientation Abusers

*Code that is nominally object-oriented but applies inheritance, polymorphism, and encapsulation incorrectly or not at all.*

### Switch Statements

- **What**: A sprawling switch or if/else-if chain that branches on a type code or kind field.
- **Signs**: The same branch set reappears in several places; every new variant means hunting down and editing each copy.
- **Why**: Conditional dispatch is written by hand where polymorphism should be doing the dispatching.
- **Fix gist**: Isolate the conditional into its own method, move it onto the class that owns the data it switches on, then replace the branches with polymorphic subclasses or strategy objects — using a null object for the empty case.
- **Treatments**: [Extract Method](refactoring-techniques.md#extract-method), [Move Method](refactoring-techniques.md#move-method), [Replace Type Code with Subclasses](refactoring-techniques.md#replace-type-code-with-subclasses), [Replace Type Code with State-Strategy](refactoring-techniques.md#replace-type-code-with-state-strategy), [Replace Conditional with Polymorphism](refactoring-techniques.md#replace-conditional-with-polymorphism), [Replace Parameter with Explicit Methods](refactoring-techniques.md#replace-parameter-with-explicit-methods), [Introduce Null Object](refactoring-techniques.md#introduce-null-object)
- **Payoff**: New variants are added by writing a class, not by editing every conditional.
- **Ignore when**: The switch is short and stable, or it is the dispatch point of a factory.

### Temporary Field

- **What**: A field that only holds a meaningful value during one particular operation and is empty the rest of the time.
- **Signs**: Fields set at the top of one algorithm and unused elsewhere; readers cannot tell when the value is valid.
- **Why**: Fields were used as a back channel to avoid threading many arguments through a complicated algorithm.
- **Fix gist**: Move the field and the code that uses it into a class of their own — typically a method object for that algorithm — or, if the emptiness itself is the condition being checked, introduce a null object.
- **Treatments**: [Extract Class](refactoring-techniques.md#extract-class), [Replace Method with Method Object](refactoring-techniques.md#replace-method-with-method-object), [Introduce Null Object](refactoring-techniques.md#introduce-null-object)
- **Payoff**: Object state is always meaningful; the algorithm's inputs become explicit.

### Refused Bequest

- **What**: A subclass that inherits a parent's interface but wants almost none of it.
- **Signs**: Inherited methods sit unused or are overridden to do nothing or raise "not supported"; the subclass is not substitutable for its parent.
- **Why**: Inheritance was chosen purely to reuse a few lines of code between classes that are not conceptually related.
- **Fix gist**: If the classes are genuinely unrelated, drop the inheritance and hold the former parent as a field, delegating only the parts actually used; if they do share something real, lift only that shared part into a new common superclass.
- **Treatments**: [Replace Inheritance with Delegation](refactoring-techniques.md#replace-inheritance-with-delegation), [Extract Superclass](refactoring-techniques.md#extract-superclass)
- **Payoff**: The hierarchy states real relationships, so design intent stops being misleading.

### Alternative Classes with Different Interfaces

- **What**: Two classes do the same job but expose it under different method names and shapes.
- **Signs**: Duplicate-looking implementations that cannot be swapped for one another; callers pick one arbitrarily.
- **Why**: Whoever wrote the second class did not know the first one already existed.
- **Fix gist**: Align the two interfaces — rename methods, add or parameterize arguments until the signatures match, move any missing behaviour across — then extract a shared superclass and delete the redundant class.
- **Treatments**: [Rename Method](refactoring-techniques.md#rename-method), [Move Method](refactoring-techniques.md#move-method), [Add Parameter](refactoring-techniques.md#add-parameter), [Parameterize Method](refactoring-techniques.md#parameterize-method), [Extract Superclass](refactoring-techniques.md#extract-superclass)
- **Payoff**: One implementation instead of two; callers stop guessing which class to use.
- **Ignore when**: The duplicates live in separately versioned third-party libraries you do not control.

## Change Preventers

*Structural faults that make one conceptual change ripple into many edits — the direct tax on future development speed.*

### Divergent Change

- **What**: One class that has to be edited for many unrelated reasons.
- **Signs**: A single class changes for feature A on Monday and feature B on Tuesday, touching different method groups each time.
- **Why**: Unrelated responsibilities were allowed to accumulate in one class instead of being separated as they appeared.
- **Fix gist**: Identify the distinct reasons the class changes and split each one out — into a separate class, or into a superclass/subclass pair when the variation is behavioural.
- **Treatments**: [Extract Class](refactoring-techniques.md#extract-class), [Extract Superclass](refactoring-techniques.md#extract-superclass), [Extract Subclass](refactoring-techniques.md#extract-subclass)
- **Payoff**: Each class has one reason to change; edits stay local and duplication drops.

### Shotgun Surgery

- **What**: The inverse of divergent change — one small conceptual change forces tiny edits in many classes.
- **Signs**: A routine tweak spreads across a long list of files; it is easy to miss a site and ship a half-applied change.
- **Why**: A single responsibility was scattered across classes, often by over-splitting during earlier refactoring.
- **Fix gist**: Pull the scattered behaviour and its data back together — move the methods and fields into one class, and inline classes that no longer justify their existence.
- **Treatments**: [Move Method](refactoring-techniques.md#move-method), [Move Field](refactoring-techniques.md#move-field), [Inline Class](refactoring-techniques.md#inline-class)
- **Payoff**: Changes land in one place; the risk of missing a site disappears.

### Parallel Inheritance Hierarchies

- **What**: Two hierarchies that must grow in lockstep — every subclass here demands a matching subclass there.
- **Signs**: Class names mirror each other across two trees; adding one variant always means adding two classes.
- **Why**: Two hierarchies were grown independently while actually encoding the same variation.
- **Fix gist**: Make one hierarchy reference instances of the other, then move the duplicated methods and fields across so that only a single hierarchy varies.
- **Treatments**: [Move Method](refactoring-techniques.md#move-method), [Move Field](refactoring-techniques.md#move-field)
- **Payoff**: One tree to extend instead of two; the mirrored duplication vanishes.
- **Ignore when**: Collapsing the duplication would leave a structure messier than the parallel trees.

## Dispensables

*Things whose absence would make the code better — redundancy, emptiness, and code kept for no live reason.*

### Comments

- **What**: Explanatory comments used as a substitute for code that says what it does.
- **Signs**: A method opens with a paragraph explaining itself; blocks are labelled by comment instead of being named methods.
- **Why**: Writing a comment feels quicker than restructuring the code that needed explaining.
- **Fix gist**: Turn the explanation into structure — name the condition with an explaining variable, extract the described block into a method named after the comment, rename anything whose name misled, and express a stated precondition as an assertion.
- **Treatments**: [Extract Variable](refactoring-techniques.md#extract-variable), [Extract Method](refactoring-techniques.md#extract-method), [Rename Method](refactoring-techniques.md#rename-method), [Introduce Assertion](refactoring-techniques.md#introduce-assertion)
- **Payoff**: The code documents itself and cannot drift out of sync with its own prose.
- **Ignore when**: The comment records why a decision was made, or explains a genuinely complex algorithm that resists simplification.

### Duplicate Code

- **What**: The same logic, exactly or nearly, existing in two or more places.
- **Signs**: Blocks that differ only in names or a constant; parallel bug fixes needed in several files; sibling classes with matching methods.
- **Why**: Copy-paste under deadline pressure, or several developers independently solving the same problem.
- **Fix gist**: Unify the copies — extract a shared method for identical fragments, pull common members up into a superclass for sibling classes, use a template method where the steps match but details differ, and merge duplicated conditional logic.
- **Treatments**: [Extract Method](refactoring-techniques.md#extract-method), [Pull Up Field](refactoring-techniques.md#pull-up-field), [Pull Up Constructor Body](refactoring-techniques.md#pull-up-constructor-body), [Form Template Method](refactoring-techniques.md#form-template-method), [Substitute Algorithm](refactoring-techniques.md#substitute-algorithm), [Extract Superclass](refactoring-techniques.md#extract-superclass), [Extract Class](refactoring-techniques.md#extract-class), [Consolidate Conditional Expression](refactoring-techniques.md#consolidate-conditional-expression), [Consolidate Duplicate Conditional Fragments](refactoring-techniques.md#consolidate-duplicate-conditional-fragments)
- **Payoff**: One place to fix, one place to read; the codebase shrinks.
- **Ignore when**: Rarely, merging two look-alike fragments makes the result harder to follow than leaving them apart.

### Lazy Class

- **What**: A class that does too little to pay back the cost of understanding and maintaining it.
- **Signs**: Almost no state or behaviour left after earlier refactoring; a subclass that adds essentially nothing.
- **Why**: A refactoring shrank the class and stopped short, or the class was created for a future that never arrived.
- **Fix gist**: Fold the class into its only caller, or collapse a near-empty subclass into its parent.
- **Treatments**: [Inline Class](refactoring-techniques.md#inline-class), [Collapse Hierarchy](refactoring-techniques.md#collapse-hierarchy)
- **Payoff**: Fewer moving parts to navigate and maintain.
- **Ignore when**: The thin class deliberately marks a seam that upcoming work will fill.

### Data Class

- **What**: A class that is only fields plus accessors, with no behaviour of its own.
- **Signs**: Public fields or mechanical getter/setter pairs; other classes constantly read its data to compute things about it.
- **Why**: Data was modelled without asking which operations belong next to it.
- **Fix gist**: Close the class down — encapsulate fields and collections, drop setters for values that must not change after construction, then move the methods that manipulate this data (or extracted parts of them) into the class and hide anything not needed outside.
- **Treatments**: [Encapsulate Field](refactoring-techniques.md#encapsulate-field), [Encapsulate Collection](refactoring-techniques.md#encapsulate-collection), [Move Method](refactoring-techniques.md#move-method), [Extract Method](refactoring-techniques.md#extract-method), [Remove Setting Method](refactoring-techniques.md#remove-setting-method), [Hide Method](refactoring-techniques.md#hide-method)
- **Payoff**: Operations on the data live with the data; duplicated computations collapse into one method.

### Dead Code

- **What**: Variables, parameters, fields, methods, or classes that nothing calls or reads any more.
- **Signs**: Zero references outside their own definition; conditional branches that can never be reached.
- **Why**: Requirements moved on and the code they made obsolete was never cleaned up.
- **Fix gist**: Delete it, leaning on version control to recover anything needed later; for unused classes and hierarchies inline or collapse them first, and strip parameters no caller supplies a meaningful value for.
- **Treatments**: [Inline Class](refactoring-techniques.md#inline-class), [Collapse Hierarchy](refactoring-techniques.md#collapse-hierarchy), [Remove Parameter](refactoring-techniques.md#remove-parameter)
- **Payoff**: Less code to read, compile, and mistrust.

### Speculative Generality

- **What**: Abstractions, hooks, and parameters added for requirements that never came.
- **Signs**: Abstract classes with one implementation; unused hook methods and parameters; indirection with no second case behind it.
- **Why**: Code written "just in case" to support imagined future needs.
- **Fix gist**: Remove the unused flexibility — collapse a hierarchy with only one real branch, inline classes and methods that just forward, and delete parameters nobody varies.
- **Treatments**: [Collapse Hierarchy](refactoring-techniques.md#collapse-hierarchy), [Inline Class](refactoring-techniques.md#inline-class), [Inline Method](refactoring-techniques.md#inline-method), [Remove Parameter](refactoring-techniques.md#remove-parameter)
- **Payoff**: Slimmer code that describes what the system actually does today.
- **Ignore when**: You are building a framework whose extension points serve external users, or the seam exists to make testing possible.

## Couplers

*Classes that know too much about one another, so neither can be changed or reused alone.*

### Feature Envy

- **What**: A method more interested in another class's data than in the data of its own class.
- **Signs**: Repeated calls to another object's getters within one method; the method reads mostly like a script operating on the foreign object.
- **Why**: Fields were moved into a data class without moving the operations that use them.
- **Fix gist**: Move the method to the class whose data it works on; if only part of it is envious, extract that part first and move just the extracted method.
- **Treatments**: [Move Method](refactoring-techniques.md#move-method), [Extract Method](refactoring-techniques.md#extract-method)
- **Payoff**: Behaviour sits with its data, killing duplication and shortening call chains.
- **Ignore when**: The separation is deliberate so behaviour can be swapped at runtime, as in Strategy or Visitor.

### Inappropriate Intimacy

- **What**: Two classes that dig into each other's private parts instead of talking through public interfaces.
- **Signs**: One class reaches for the other's internals; bidirectional references; changing either class breaks the other.
- **Why**: The boundary between the two was never enforced, so encapsulation eroded.
- **Fix gist**: Redraw the boundary — move the methods and fields to whichever class truly owns them, extract shared parts into a new class, hide navigation behind a delegating method, cut the association down to one direction, and where one class really is a specialization of the other, use inheritance.
- **Treatments**: [Move Method](refactoring-techniques.md#move-method), [Move Field](refactoring-techniques.md#move-field), [Extract Class](refactoring-techniques.md#extract-class), [Hide Delegate](refactoring-techniques.md#hide-delegate), [Change Bidirectional Association to Unidirectional](refactoring-techniques.md#change-bidirectional-association-to-unidirectional), [Replace Delegation with Inheritance](refactoring-techniques.md#replace-delegation-with-inheritance)
- **Payoff**: Independently understandable, testable, reusable classes.

### Message Chains

- **What**: A call sequence that hops object to object — `a.getB().getC().doSomething()`.
- **Signs**: Long dotted chains at call sites; the caller must know the shape of an object graph it does not own.
- **Why**: Clients navigate the structure themselves instead of asking the nearest object for the result.
- **Fix gist**: Add a delegating method on the first object so callers ask it directly; if a caller only needs a computed result, extract that computation into a method and move it to the object holding the data.
- **Treatments**: [Hide Delegate](refactoring-techniques.md#hide-delegate), [Extract Method](refactoring-techniques.md#extract-method), [Move Method](refactoring-techniques.md#move-method)
- **Payoff**: Callers stop depending on the internal object graph; restructuring it no longer breaks them.
- **Ignore when**: Hiding every hop buries where work happens and breeds middle men — stop before that point.

### Middle Man

- **What**: A class whose methods almost all just forward to another object.
- **Signs**: Nearly every method is a one-line delegation; the class adds no logic of its own.
- **Why**: Over-eager delegate hiding, or responsibilities that gradually drained away to another class.
- **Fix gist**: Delete the intermediary and let callers talk to the real object directly.
- **Treatments**: [Remove Middle Man](refactoring-techniques.md#remove-middle-man)
- **Payoff**: One less hop to trace and one less class to maintain.
- **Ignore when**: The delegation is deliberate — a Proxy or Decorator, or a seam that keeps two subsystems from depending on each other.

## Other Smells

*Problems that fit none of the categories above.*

### Incomplete Library Class

- **What**: A third-party library that almost does what you need, but you cannot change its source.
- **Signs**: Wrapper code and copy-pasted workarounds gather around the library; the missing behaviour is reimplemented in several callers.
- **Why**: The library authors never implemented the feature, or turned the request down.
- **Fix gist**: Add the missing behaviour once, outside the library — a single helper method taking the library object as an argument for one or two additions, or a subclass or wrapper class when you need a set of them.
- **Treatments**: [Introduce Foreign Method](refactoring-techniques.md#introduce-foreign-method), [Introduce Local Extension](refactoring-techniques.md#introduce-local-extension)
- **Payoff**: You keep using the library instead of rewriting it, and the patch lives in one place.
- **Ignore when**: Maintaining the extension against library upgrades would cost more than it saves.
