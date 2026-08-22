# Refactoring Techniques Reference

> **Provenance**: Condensed and paraphrased (original wording, no verbatim text) from Refactoring.Guru — index: https://refactoring.guru/refactoring/techniques, entries: `https://refactoring.guru/<slug>`. Crawled 2026-07-29. Source pages carry full code examples; only language-agnostic mechanics are kept here.
>
> **Companion**: [code-smells.md](code-smells.md). **Fixes smells** links resolve there; this file stands alone for applying a known technique.
>
> **How to use** — Refactoring agents: follow **Mechanics** step by step; read **Drawbacks** first. Planning agents: pick techniques via **Problem** and **Fixes smells**, then sequence them. Reviewer agents: cite a technique anchor (e.g. `refactoring-techniques.md#extract-method`) as the concrete recommendation for a finding.

## Contents

- [Composing Methods](#composing-methods) (9)
- [Moving Features between Objects](#moving-features-between-objects) (8)
- [Organizing Data](#organizing-data) (15)
- [Simplifying Conditional Expressions](#simplifying-conditional-expressions) (8)
- [Simplifying Method Calls](#simplifying-method-calls) (14)
- [Dealing with Generalization](#dealing-with-generalization) (12)

## Composing Methods

### Extract Method

- **Problem**: A code fragment can be understood on its own but lives inside a larger method.
- **Solution**: Move the fragment to a new method whose name states its purpose; call it from the original site.
- **Why**: The root move behind most other refactorings — shorter methods, self-documenting call sites, reusable logic.
- **Mechanics**:
  1. Create a method named for what the fragment does, not how.
  2. Move the fragment into it, leaving a call behind.
  3. Pass locals the fragment reads as parameters.
  4. If the fragment writes one local, return it; if several, extract smaller pieces instead.
- **Benefits**: Readability, deduplication, isolated change points. **Drawbacks**: Over-extraction scatters trivial logic across many tiny methods.
- **Fixes smells**: [Long Method](code-smells.md#long-method), [Duplicate Code](code-smells.md#duplicate-code), [Comments](code-smells.md#comments), [Feature Envy](code-smells.md#feature-envy), [Switch Statements](code-smells.md#switch-statements), [Message Chains](code-smells.md#message-chains), [Data Class](code-smells.md#data-class)

### Inline Method

- **Problem**: A method's body is as clear as its name, so the indirection buys nothing.
- **Solution**: Paste the body into every call site and delete the method.
- **Why**: Chains of trivial delegating methods obscure where work actually happens.
- **Mechanics**:
  1. Confirm the method is not overridden in any subclass; if it is, stop.
  2. Find every call site.
  3. Substitute the method body for each call.
  4. Delete the now-unused method.
- **Benefits**: Fewer hops to follow for straightforward logic. **Drawbacks**: Loses a name that may have carried meaning.
- **Fixes smells**: [Speculative Generality](code-smells.md#speculative-generality)

### Extract Variable

- **Problem**: A dense expression is hard to parse at a glance.
- **Solution**: Assign parts of it to variables whose names explain what each part means.
- **Why**: Naming the pieces removes the need for an explanatory comment.
- **Mechanics**:
  1. Declare a new variable just before the complex expression.
  2. Assign one self-contained sub-expression to it.
  3. Substitute the variable for that sub-expression in place.
  4. Repeat until each remaining part is readable.
- **Benefits**: Self-explaining conditions and calculations. **Drawbacks**: Extra variables, and eager evaluation can defeat short-circuiting.
- **Fixes smells**: [Comments](code-smells.md#comments)

### Inline Temp

- **Problem**: A variable holds a simple expression and is read only once.
- **Solution**: Replace the reference with the expression itself and drop the variable.
- **Why**: Clears the way for Replace Temp with Query or Extract Method.
- **Mechanics**:
  1. Confirm the variable is assigned once and the expression is side-effect free.
  2. Find its uses.
  3. Substitute the assigned expression for each use.
  4. Delete the declaration and assignment.
- **Benefits**: Slightly shorter, less cluttered code. **Drawbacks**: Do not inline a variable caching an expensive call — it would be recomputed.
- **Fixes smells**: —

### Replace Temp with Query

- **Problem**: A local variable stores the result of an expression that other code could also use.
- **Solution**: Extract the expression into a query method and call it wherever the temp was read.
- **Why**: The value becomes reusable outside the method and gains an explanatory name.
- **Mechanics**:
  1. Check the variable is assigned exactly once; split it first if not.
  2. Extract the right-hand expression into its own method.
  3. Make sure that method only computes and returns — no state changes.
  4. Replace every read of the variable with a call, then remove the variable.
- **Benefits**: Readability and reuse across methods. **Drawbacks**: An extra call per read, usually negligible.
- **Fixes smells**: [Long Method](code-smells.md#long-method), [Duplicate Code](code-smells.md#duplicate-code)

### Split Temporary Variable

- **Problem**: One local variable is reused to hold several unrelated values.
- **Solution**: Give each purpose its own variable, named for what it holds.
- **Why**: A recycled variable forces readers to track which meaning is live at each line.
- **Mechanics**:
  1. Find the first assignment and rename the variable after the value it holds there.
  2. Update the references belonging to that first value.
  3. Declare a fresh variable at the next assignment with its own name.
  4. Repeat for each distinct value the original variable carried.
- **Benefits**: One responsibility per variable; unblocks later extraction. **Drawbacks**: None of note.
- **Fixes smells**: —

### Remove Assignments to Parameters

- **Problem**: A method reassigns one of its own parameters.
- **Solution**: Assign to a local variable initialized from the parameter instead.
- **Why**: A reused parameter hides what was passed in and can surprise callers under by-reference semantics.
- **Mechanics**:
  1. Declare a local variable inside the method.
  2. Initialize it with the parameter's incoming value.
  3. Point all code after that assignment at the local variable.
  4. Verify the parameter is now only read, never written.
- **Benefits**: Argument values stay meaningful throughout; extraction becomes safe. **Drawbacks**: None of note.
- **Fixes smells**: —

### Replace Method with Method Object

- **Problem**: A long method's locals are so entangled that Extract Method cannot be applied.
- **Solution**: Turn the method into its own class, with the locals as fields.
- **Why**: Once locals are fields, the method can be broken up freely without polluting the original class.
- **Mechanics**:
  1. Create a class named after the method's job.
  2. Give it a field referencing the original object plus a field per local variable.
  3. Add a constructor taking the original object and the method's parameters.
  4. Copy the body into a single execution method, reading fields instead of locals.
  5. Replace the original method with construction plus a call to that method.
  6. Now decompose the execution method with Extract Method.
- **Benefits**: Unlocks decomposition of otherwise untouchable methods. **Drawbacks**: Adds a class, so total complexity rises.
- **Fixes smells**: [Long Method](code-smells.md#long-method)

### Substitute Algorithm

- **Problem**: An algorithm should be replaced by a clearer or faster one.
- **Solution**: Swap the method body for the new implementation.
- **Why**: Incremental cleanup is sometimes slower than rewriting, especially when a library already solves the problem.
- **Mechanics**:
  1. Ensure the method is covered by tests, and move any incidental work out of it first.
  2. Write the replacement algorithm as a separate method.
  3. Swap it in and run the tests.
  4. Where results differ, compare old and new outputs case by case until they agree.
  5. Delete the old implementation.
- **Benefits**: Simpler or faster code in one step. **Drawbacks**: Risky without tests — behavioural differences can slip through.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code), [Long Method](code-smells.md#long-method)

## Moving Features between Objects

### Move Method

- **Problem**: A method is used more by another class than by the one that hosts it.
- **Solution**: Recreate it in the class that uses it most and turn the original into a delegation or delete it.
- **Why**: Puts behaviour next to the data it needs, raising cohesion and cutting cross-class traffic.
- **Mechanics**:
  1. List the features the method depends on; plan to move any that belong with it.
  2. Check whether the method is declared in a supertype or overridden below — leave polymorphic methods alone.
  3. Create the method in the recipient class, renaming it to fit if appropriate.
  4. Ensure the source object can reach the recipient (field, parameter, or existing reference).
  5. Turn the old method into a delegating call, or delete it outright.
  6. Repoint callers at the new location.
- **Benefits**: Higher cohesion, looser coupling. **Drawbacks**: Needs careful dependency analysis when the method shares state with its old home.
- **Fixes smells**: [Shotgun Surgery](code-smells.md#shotgun-surgery), [Feature Envy](code-smells.md#feature-envy), [Switch Statements](code-smells.md#switch-statements), [Parallel Inheritance Hierarchies](code-smells.md#parallel-inheritance-hierarchies), [Message Chains](code-smells.md#message-chains), [Inappropriate Intimacy](code-smells.md#inappropriate-intimacy), [Data Class](code-smells.md#data-class)

### Move Field

- **Problem**: A field is read and written mostly by another class.
- **Solution**: Declare it in that class and route every access through it.
- **Why**: Data should live with the methods that actually use it.
- **Mechanics**:
  1. If the field is public, encapsulate it behind accessors first.
  2. Declare the field and its accessors in the destination class.
  3. Make sure the source object can reach the destination object.
  4. Replace every use of the old field with calls to the destination's accessors.
  5. Delete the original field.
- **Benefits**: Cleaner ownership of data, fewer indirect dependencies. **Drawbacks**: Fields used across an inheritance hierarchy need extra care.
- **Fixes smells**: [Shotgun Surgery](code-smells.md#shotgun-surgery), [Parallel Inheritance Hierarchies](code-smells.md#parallel-inheritance-hierarchies), [Inappropriate Intimacy](code-smells.md#inappropriate-intimacy)

### Extract Class

- **Problem**: One class is doing the work of two.
- **Solution**: Create a second class and move the fields and methods of one responsibility into it.
- **Why**: Classes accumulate duties until no one can safely change them; splitting restores a single reason to change.
- **Mechanics**:
  1. Decide exactly how the responsibilities divide.
  2. Create the new class for the split-off responsibility.
  3. Link old to new, preferring a one-way reference.
  4. Move fields and methods across with Move Field and Move Method, private members first.
  5. Re-run tests after each move.
  6. Decide whether the new class is exposed publicly or kept internal.
- **Benefits**: Focused, reliable, independently changeable classes. **Drawbacks**: Splitting too eagerly produces classes so thin they must be inlined again.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code), [Large Class](code-smells.md#large-class), [Divergent Change](code-smells.md#divergent-change), [Data Clumps](code-smells.md#data-clumps), [Primitive Obsession](code-smells.md#primitive-obsession), [Temporary Field](code-smells.md#temporary-field), [Inappropriate Intimacy](code-smells.md#inappropriate-intimacy)

### Inline Class

- **Problem**: A class does almost nothing and has no future duties planned.
- **Solution**: Fold its features into the class that uses it and delete it.
- **Why**: Every class costs attention; one that earns nothing should go.
- **Mechanics**:
  1. Copy the donor's public interface onto the recipient class.
  2. Repoint every reference to the donor at the recipient.
  3. Run tests.
  4. Move the remaining members across with Move Method and Move Field.
  5. Delete the emptied class.
- **Benefits**: Fewer classes and hops. **Drawbacks**: The migration must be complete or callers break.
- **Fixes smells**: [Shotgun Surgery](code-smells.md#shotgun-surgery), [Lazy Class](code-smells.md#lazy-class), [Speculative Generality](code-smells.md#speculative-generality)

### Hide Delegate

- **Problem**: Clients call through a server object to reach a delegate object behind it.
- **Solution**: Add methods on the server that forward to the delegate, so clients never see it.
- **Why**: Clients stop depending on the internal object graph, which is then free to change.
- **Mechanics**:
  1. Identify which delegate operations clients actually use.
  2. Add a delegating method on the server for each one.
  3. Switch clients to the new server methods.
  4. Remove the accessor exposing the delegate once nothing needs it.
- **Benefits**: Encapsulated structure; restructuring no longer ripples to callers. **Drawbacks**: Too many forwarding methods turn the server into a Middle Man.
- **Fixes smells**: [Message Chains](code-smells.md#message-chains), [Inappropriate Intimacy](code-smells.md#inappropriate-intimacy)

### Remove Middle Man

- **Problem**: A class does little except forward calls to another object.
- **Solution**: Expose the delegate and let clients call it directly.
- **Why**: The intermediary adds no behaviour yet must be updated every time the delegate grows.
- **Mechanics**:
  1. Add a getter on the server that returns the delegate.
  2. Locate every client call to a delegating method.
  3. Rewrite each as a call on the delegate obtained from the getter.
  4. Delete the delegating methods.
- **Benefits**: One less layer to maintain. **Drawbacks**: Clients now couple to the delegate directly.
- **Fixes smells**: [Middle Man](code-smells.md#middle-man)

### Introduce Foreign Method

- **Problem**: A utility class you cannot modify is missing a method you keep needing.
- **Solution**: Write that method in the client class, taking the utility object as an argument.
- **Why**: Stops the same snippet being pasted at every call site.
- **Mechanics**:
  1. Add a method to the client class doing what the utility class should do.
  2. Give it a parameter for the utility object and operate on that.
  3. Move the repeated logic into it and call it from the former sites.
  4. Comment that it is a foreign method belonging elsewhere.
- **Benefits**: Removes duplication with minimal machinery. **Drawbacks**: Misplaced code confuses later readers; several such methods mean you should extend the class instead.
- **Fixes smells**: [Incomplete Library Class](code-smells.md#incomplete-library-class)

### Introduce Local Extension

- **Problem**: A utility class you cannot change lacks several methods you need.
- **Solution**: Create a subclass or wrapper that adds them and use it in place of the original.
- **Why**: Keeps the additions in one coherent, reusable place rather than scattered across clients.
- **Mechanics**:
  1. Choose a subclass (simpler) or a wrapper (needed when the class is final or instances arrive from elsewhere).
  2. Give the extension constructors mirroring the original's.
  3. Add a converting constructor that takes an existing instance of the original.
  4. Implement the new methods on the extension.
  5. Replace uses of the original with the extension where the extras are needed.
- **Benefits**: Additions stay together and can be reused. **Drawbacks**: A wrapper needs delegating methods and must handle identity carefully.
- **Fixes smells**: [Incomplete Library Class](code-smells.md#incomplete-library-class)

## Organizing Data

### Self Encapsulate Field

- **Problem**: Code inside a class touches its own private field directly.
- **Solution**: Read and write the field through the class's own getter and setter.
- **Why**: An accessor is a hook — for lazy initialization, validation, or subclass overriding — that direct access denies you.
- **Mechanics**:
  1. Add a getter, and a setter if the field is written.
  2. Find every direct use of the field inside the class.
  3. Replace reads with the getter and writes with the setter.
  4. Leave only the accessors touching the field itself.
- **Benefits**: Field access becomes a customization point. **Drawbacks**: More ceremony than plain field access for no immediate gain.
- **Fixes smells**: —

### Replace Data Value with Object

- **Problem**: A primitive field has grown behaviour and companion data around it, repeated across classes.
- **Solution**: Give the value its own class and hold an instance of it instead.
- **Why**: Collects the scattered logic about that value into one place.
- **Mechanics**:
  1. Create a class holding the value, with a getter and a constructor taking it.
  2. Change the original field's type to the new class.
  3. Make the original getter delegate to the new object's getter.
  4. Make the original setter construct a new instance.
  5. Move the related behaviour into the new class.
- **Benefits**: Related data and behaviour travel together. **Drawbacks**: For genuinely shared or identity-bearing data, follow up with Change Value to Reference.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code)

### Change Value to Reference

- **Problem**: Many equal copies of the same conceptual object exist where one shared instance is wanted.
- **Solution**: Replace the copies with references to a single instance.
- **Why**: When the data must be updated and every holder must see the update, copies cannot work.
- **Mechanics**:
  1. Replace direct construction with a factory method.
  2. Add a registry (map or store) that owns the instances.
  3. Decide whether instances are preloaded or created on first request.
  4. Have the factory return the existing instance, creating and registering it when absent.
- **Benefits**: One authoritative object; updates are visible everywhere. **Drawbacks**: Lifecycle, identity, and cleanup all get harder.
- **Fixes smells**: —

### Change Reference to Value

- **Problem**: A shared reference object is small and effectively unchanging, yet still needs managing.
- **Solution**: Make it an immutable value that is freely copied and compared by content.
- **Why**: Registries and identity management are pure overhead when the data never changes.
- **Mechanics**:
  1. Remove setters and any method that mutates state.
  2. Set all state in the constructor only.
  3. Implement value-based equality (and hashing where the language needs it).
  4. Make the constructor public and retire the factory and registry.
- **Benefits**: Simpler code, safe sharing across threads and processes. **Drawbacks**: Wrong choice if the object ever must change — copies cannot be kept in sync.
- **Fixes smells**: —

### Replace Array with Object

- **Problem**: An array holds unrelated items of different meanings, addressed by index.
- **Solution**: Replace it with a class whose named fields describe each item.
- **Why**: Index-addressed heterogeneous data is easy to fill in wrong and impossible to read.
- **Mechanics**:
  1. Create a class to represent the array's contents.
  2. Keep the array inside it initially and add a named accessor per element.
  3. Repoint all callers at the named accessors.
  4. Make the array private once nothing reads it directly.
  5. Replace each array slot with a real typed field, then delete the array.
- **Benefits**: Self-documenting data plus a home for related behaviour. **Drawbacks**: Every access site must be migrated.
- **Fixes smells**: [Primitive Obsession](code-smells.md#primitive-obsession)

### Duplicate Observed Data

- **Problem**: Domain data lives inside a GUI class.
- **Solution**: Move the data into a domain class and keep the two in step with the Observer pattern.
- **Why**: Domain logic trapped in the interface cannot be reused, tested, or given a second front end.
- **Mechanics**:
  1. Encapsulate the GUI fields behind accessors.
  2. Create a domain class mirroring those fields.
  3. Have the domain class keep an observer list and the GUI class implement the update callback.
  4. Register the GUI as an observer of the domain object.
  5. Make domain setters notify observers; make GUI setters write through to the domain.
- **Benefits**: Separated presentation and domain; multiple views become possible. **Drawbacks**: Pointless where objects are rebuilt per request, as in typical web apps.
- **Fixes smells**: [Large Class](code-smells.md#large-class)

### Change Unidirectional Association to Bidirectional

- **Problem**: Two classes are linked one way, but the target now needs to reach back.
- **Solution**: Add the reverse reference and keep both sides consistent.
- **Why**: New requirements need navigation in the other direction, and re-deriving it is expensive.
- **Mechanics**:
  1. Add the back-reference field to the class that lacks it.
  2. Pick one class as dominant — it owns updates to the association.
  3. Give the non-dominant class a helper that sets its side of the link.
  4. Have the dominant class's setter update both sides through that helper.
- **Benefits**: Cheap navigation in both directions. **Drawbacks**: Both ends must be kept in sync, and the classes can no longer be used apart.
- **Fixes smells**: —

### Change Bidirectional Association to Unidirectional

- **Problem**: Two classes point at each other but one side never uses its reference.
- **Solution**: Delete the unused direction.
- **Why**: Two-way links cost synchronization code, tighten coupling, and keep objects alive longer than needed.
- **Mechanics**:
  1. Confirm the field is genuinely unused, or that its value can be obtained another way.
  2. Where it is still needed, supply the object as a method parameter or look it up instead.
  3. Remove the code that assigns the back-reference.
  4. Delete the field.
- **Benefits**: Simpler classes that can be used and tested independently. **Drawbacks**: None of note once the reference is truly unused.
- **Fixes smells**: [Inappropriate Intimacy](code-smells.md#inappropriate-intimacy)

### Replace Magic Number with Symbolic Constant

- **Problem**: A bare literal appears in code with no indication of what it means.
- **Solution**: Name it as a constant and use the constant everywhere.
- **Why**: The name explains the value, and changing it later becomes a one-line edit rather than a search.
- **Mechanics**:
  1. Declare a constant initialized to the literal, named for its meaning.
  2. Find every occurrence of that literal.
  3. Check each one actually means the same thing — identical values often are not.
  4. Replace the matching occurrences with the constant.
- **Benefits**: Self-documenting values and safe global updates. **Drawbacks**: Self-evident literals need no name, and type codes call for a dedicated technique instead.
- **Fixes smells**: [Primitive Obsession](code-smells.md#primitive-obsession)

### Encapsulate Field

- **Problem**: A field is public, so anything can read or write it unchecked.
- **Solution**: Make it private and expose it through accessors.
- **Why**: Control over access is what lets you validate, log, or later change the representation.
- **Mechanics**:
  1. Add a getter and, if writes are needed, a setter.
  2. Replace external reads with the getter.
  3. Replace external writes with the setter.
  4. Make the field private.
- **Benefits**: Real encapsulation and a place to attach behaviour. **Drawbacks**: In measured hot paths with huge object counts, accessor overhead can matter.
- **Fixes smells**: [Data Class](code-smells.md#data-class)

### Encapsulate Collection

- **Problem**: A class hands out its collection through a plain getter and setter, so callers mutate it freely.
- **Solution**: Return a read-only view and offer explicit add and remove methods.
- **Why**: The owner cannot maintain invariants over a collection anyone can modify behind its back.
- **Mechanics**:
  1. Add methods for adding and removing single elements.
  2. Make sure the field is initialized to an empty collection.
  3. Replace setter calls with a sequence of add/remove calls, then drop the setter.
  4. Repoint callers that mutated through the getter at the new methods.
  5. Change the getter to return an unmodifiable or copied view.
  6. Look for caller logic that belongs inside the owning class and move it in.
- **Benefits**: The owner keeps control and can add domain-specific collection operations. **Drawbacks**: None of note.
- **Fixes smells**: [Data Class](code-smells.md#data-class)

### Replace Type Code with Class

- **Problem**: A number or string field encodes a type, with no validation or type safety.
- **Solution**: Turn the type code into a class whose instances are the only legal values.
- **Why**: Arbitrary values can be assigned to a plain int or string, and the compiler cannot help.
- **Mechanics**:
  1. Create a class named for the concept the code represents.
  2. Give it a private coded value plus a getter.
  3. Add a static instance or factory method per legal value.
  4. Change the original field's type to the new class.
  5. Update all readers and writers to use the class's values.
  6. Remove the old constants.
- **Benefits**: Type-checked values and one home for type-related logic. **Drawbacks**: Wrong choice when the code drives branching behaviour — use subclasses or state objects instead.
- **Fixes smells**: [Primitive Obsession](code-smells.md#primitive-obsession)

### Replace Type Code with Subclasses

- **Problem**: A type code selects different behaviour through conditionals scattered around the class.
- **Solution**: Make a subclass per code value and let polymorphism choose the behaviour.
- **Why**: Behaviour keyed by a code spreads branching everywhere; subclasses localize each variant.
- **Mechanics**:
  1. Self-encapsulate the type code field.
  2. Make the superclass constructor private and add a static factory that picks a subclass by code.
  3. Create one subclass per value, each overriding the code getter.
  4. Delete the code field and make the getter abstract.
  5. Push variant-specific fields and methods down into the subclasses.
  6. Replace the conditionals with polymorphic calls.
- **Benefits**: Conditionals disappear; new variants are new classes. **Drawbacks**: Impossible when the class already has a hierarchy, or when the code changes after construction.
- **Fixes smells**: [Primitive Obsession](code-smells.md#primitive-obsession)

### Replace Type Code with State-Strategy

- **Problem**: A type code drives behaviour, but subclassing the host class is not an option.
- **Solution**: Hold a state or strategy object chosen by the code, and delegate the varying behaviour to it.
- **Why**: Gets polymorphic dispatch where inheritance is unavailable, and lets the variant change at runtime.
- **Mechanics**:
  1. Self-encapsulate the type code field.
  2. Create an abstract state class for the concept.
  3. Add a concrete subclass per code value.
  4. Add a factory that returns the right state object for a given code.
  5. Change the field's type to the state class and route the setter through the factory.
  6. Move each conditional branch into the matching state subclass and delegate.
- **Benefits**: Behaviour can be swapped at runtime and extended without editing the host. **Drawbacks**: Overkill for a type code that carries no behaviour.
- **Fixes smells**: [Primitive Obsession](code-smells.md#primitive-obsession)

### Replace Subclass with Fields

- **Problem**: Subclasses differ only in methods that return constants.
- **Solution**: Delete them and store those constants in fields of the superclass.
- **Why**: A whole class per constant is more structure than the difference deserves.
- **Mechanics**:
  1. Give the subclasses factory methods on the superclass.
  2. Repoint client construction at those factory methods.
  3. Add a superclass field per differing constant, plus a protected constructor taking them.
  4. Have each factory pass the right values.
  5. Implement the constant-returning methods on the superclass from the fields and delete the subclass overrides.
  6. Delete the empty subclasses.
- **Benefits**: A flatter hierarchy with no loss of behaviour. **Drawbacks**: None while the difference stays data-only; reverse it if the variants gain real behaviour.
- **Fixes smells**: —

## Simplifying Conditional Expressions

### Decompose Conditional

- **Problem**: A conditional's test and branches are long enough to obscure what it decides.
- **Solution**: Extract the condition and each branch into methods named for their intent.
- **Why**: Readers should see the decision being made without parsing the mechanics of making it.
- **Mechanics**:
  1. Extract the test expression into a method with a name that reads as a question.
  2. Extract the then-branch into its own named method.
  3. Extract the else-branch likewise.
  4. Leave a conditional that is three named calls.
- **Benefits**: The decision reads as prose. **Drawbacks**: A few extra calls, negligible in practice.
- **Fixes smells**: [Long Method](code-smells.md#long-method)

### Consolidate Conditional Expression

- **Problem**: Several separate conditionals all lead to the same result.
- **Solution**: Merge them into one expression joined by boolean operators.
- **Why**: Shows that the checks are one decision, not several unrelated ones.
- **Mechanics**:
  1. Confirm none of the conditions has a side effect.
  2. Combine nested conditions with AND.
  3. Combine sequential conditions sharing a result with OR.
  4. Extract the combined test into a method whose name states what it checks.
- **Benefits**: One clearly named decision instead of scattered checks. **Drawbacks**: None of note.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code)

### Consolidate Duplicate Conditional Fragments

- **Problem**: The same code appears in every branch of a conditional.
- **Solution**: Hoist it out of the conditional entirely.
- **Why**: Code that runs regardless of the outcome does not belong inside the decision.
- **Mechanics**:
  1. Move code duplicated at the start of every branch to just before the conditional.
  2. Move code duplicated at the end of every branch to just after it.
  3. For duplicates in the middle, first shift them to a branch boundary where order allows.
  4. If the shared code is more than a line or two, extract it into a method.
- **Benefits**: Shorter branches and no duplication. **Drawbacks**: None of note.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code)

### Remove Control Flag

- **Problem**: A boolean variable exists solely to steer exit from a loop or method.
- **Solution**: Use the language's own control statements instead.
- **Why**: The flag is a workaround for a single-exit style that modern languages make unnecessary.
- **Mechanics**:
  1. Find where setting the flag is meant to end the loop or method.
  2. Replace that assignment with break, continue, or return as appropriate.
  3. Delete the flag, its declaration, and every test of it.
- **Benefits**: Much less code and an obvious flow of control. **Drawbacks**: None of note.
- **Fixes smells**: —

### Replace Nested Conditional with Guard Clauses

- **Problem**: Nested conditionals march the real logic ever further to the right.
- **Solution**: Handle each special case up front with an early return or throw, leaving the main path unindented.
- **Why**: Deep nesting hides which path is normal and which are exceptions.
- **Mechanics**:
  1. Remove side effects from the conditions first, splitting query from modifier if needed.
  2. Identify the conditions that represent special cases.
  3. Turn each into a guard at the top of the method that returns or raises immediately.
  4. Re-run tests after each move.
  5. Merge guards that share an outcome with Consolidate Conditional Expression.
- **Benefits**: Flat structure with the happy path plainly visible. **Drawbacks**: None of note.
- **Fixes smells**: [Long Method](code-smells.md#long-method), [Switch Statements](code-smells.md#switch-statements)

### Replace Conditional with Polymorphism

- **Problem**: A conditional picks different behaviour based on an object's type or state.
- **Solution**: Put each branch in a subclass method and let dispatch choose.
- **Why**: The same branch set tends to reappear elsewhere; polymorphism removes every copy at once.
- **Mechanics**:
  1. Extract the conditional into its own method if it is embedded in a larger one.
  2. Build a hierarchy with one subclass per branch.
  3. Override the method in each subclass with that branch's body.
  4. Delete branches from the original one at a time, testing as you go.
  5. When no branches remain, make the superclass method abstract.
- **Benefits**: New variants need no edits to existing code. **Drawbacks**: Requires a class hierarchy that may not otherwise be warranted.
- **Fixes smells**: [Switch Statements](code-smells.md#switch-statements)

### Introduce Null Object

- **Problem**: Null checks for the same absent value are repeated all over the code.
- **Solution**: Supply an object representing "nothing" whose methods do the default thing.
- **Why**: Absence is a case the type system can model, rather than something every caller re-tests.
- **Mechanics**:
  1. Create a subclass (or sibling implementation) standing for the null case.
  2. Give both it and the real class a way to report null-ness.
  3. Return the null object wherever null was returned.
  4. Replace null comparisons with the null-ness check.
  5. Override the null object's methods with sensible do-nothing or neutral behaviour.
  6. Delete the checks once the default behaviour covers them.
- **Benefits**: The conditionals disappear and default behaviour lives in one place. **Drawbacks**: An extra class, and a hidden null object can mask real errors.
- **Fixes smells**: [Switch Statements](code-smells.md#switch-statements), [Temporary Field](code-smells.md#temporary-field)

### Introduce Assertion

- **Problem**: A block of code silently assumes something about its inputs or state.
- **Solution**: State the assumption as an assertion.
- **Why**: The assumption becomes checked documentation instead of tribal knowledge.
- **Mechanics**:
  1. Find the assumption, often written as a comment or implied by the code.
  2. Add an assertion expressing it.
  3. Make sure the assertion has no effect on normal behaviour.
  4. Assert only conditions that must hold, not every conceivable one.
- **Benefits**: Failures surface at the cause rather than downstream. **Drawbacks**: Use exceptions instead where user or system input can legitimately violate the condition.
- **Fixes smells**: [Comments](code-smells.md#comments)

## Simplifying Method Calls

### Rename Method

- **Problem**: A method's name does not describe what it does.
- **Solution**: Rename it to say what it does.
- **Why**: Names go stale as behaviour evolves, and a misleading name is worse than a vague one.
- **Mechanics**:
  1. Check whether the method is declared in a supertype or overridden below; rename the whole family together.
  2. Create the method under the new name with the same body.
  3. Make the old method delegate to the new one.
  4. Repoint all callers at the new name.
  5. Delete the old method, or deprecate it if it is part of a published interface.
- **Benefits**: Call sites explain themselves. **Drawbacks**: None of note internally; a public API needs a deprecation period.
- **Fixes smells**: [Alternative Classes with Different Interfaces](code-smells.md#alternative-classes-with-different-interfaces), [Comments](code-smells.md#comments)

### Add Parameter

- **Problem**: A method needs information it does not currently receive.
- **Solution**: Add a parameter carrying it.
- **Why**: New requirements need data the method has no other way to reach.
- **Mechanics**:
  1. Check for declarations in supertypes and subtypes and change them consistently.
  2. Create the new method signature alongside the old one.
  3. Make the old method call the new one with a default value.
  4. Migrate callers to the new signature.
  5. Delete the old method, or deprecate it if published.
- **Benefits**: The method gets what it needs without hidden state. **Drawbacks**: Repeated use grows a Long Parameter List — prefer passing an object once several parameters accumulate.
- **Fixes smells**: —

### Remove Parameter

- **Problem**: A parameter is no longer used by the method body.
- **Solution**: Take it out of the signature.
- **Why**: An unused parameter misleads readers into thinking it matters and forces callers to invent a value.
- **Mechanics**:
  1. Verify no supertype or subtype implementation still uses it.
  2. Create the method without the parameter and have the old one delegate.
  3. Update all callers.
  4. Delete the old method, or deprecate it if published.
- **Benefits**: Honest signatures. **Drawbacks**: Care needed with polymorphic methods and public APIs.
- **Fixes smells**: [Speculative Generality](code-smells.md#speculative-generality)

### Separate Query from Modifier

- **Problem**: One method both returns a value and changes state.
- **Solution**: Split it into a query that only reads and a command that only writes.
- **Why**: Callers who just want the value should not trigger a side effect to get it.
- **Mechanics**:
  1. Add a query method that returns the value without changing anything.
  2. Have the original method call the query for its return value.
  3. At each call site, call the modifier and then the query (or just the query where no change is wanted).
  4. Strip the return value from the modifier.
- **Benefits**: Queries become safe to call repeatedly, cache, and reorder. **Drawbacks**: Loses genuinely useful combined results, such as a delete returning a count.
- **Fixes smells**: —

### Parameterize Method

- **Problem**: Several methods do the same thing apart from a few embedded values.
- **Solution**: Merge them into one method taking those values as parameters.
- **Why**: Removes near-duplicate methods and makes new variants free.
- **Mechanics**:
  1. Extract the shared logic into one method.
  2. Turn each differing literal into a parameter.
  3. Repoint callers at the parameterized method with the right arguments.
  4. Delete the redundant methods.
- **Benefits**: One implementation instead of many. **Drawbacks**: Too many parameters — especially boolean switches — make the merged method worse than the originals.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code)

### Replace Parameter with Explicit Methods

- **Problem**: A method branches on a parameter that selects one of a fixed set of behaviours.
- **Solution**: Give each behaviour its own named method and drop the selector.
- **Why**: A named method beats a call whose meaning depends on a flag argument.
- **Mechanics**:
  1. Create one method per branch, named for what that branch does.
  2. Leave the original delegating to them while you migrate.
  3. Switch each call site to the matching explicit method.
  4. Delete the original method and its parameter.
- **Benefits**: Self-documenting calls and no dispatch logic. **Drawbacks**: Not worth it when the variants are numerous or change often — parameterizing may be better.
- **Fixes smells**: [Switch Statements](code-smells.md#switch-statements), [Long Method](code-smells.md#long-method)

### Preserve Whole Object

- **Problem**: A caller pulls several values out of one object just to pass them separately.
- **Solution**: Pass the object itself.
- **Why**: When the method's data needs change, only the method changes — not every caller.
- **Mechanics**:
  1. Add a parameter for the whole object.
  2. Replace the individual parameters one at a time, having the method read from the object.
  3. Test after each replacement.
  4. Delete the unpacking code from the call sites.
- **Benefits**: Shorter signatures and callers that no longer know what the method needs. **Drawbacks**: Couples the method to that object's type, which may be undesirable.
- **Fixes smells**: [Primitive Obsession](code-smells.md#primitive-obsession), [Long Parameter List](code-smells.md#long-parameter-list), [Long Method](code-smells.md#long-method), [Data Clumps](code-smells.md#data-clumps)

### Replace Parameter with Method Call

- **Problem**: A caller computes a value by calling a query, then passes the result in as a parameter.
- **Solution**: Let the method make that query itself and drop the parameter.
- **Why**: Shorter signatures, and the caller stops needing to know how the value is obtained.
- **Mechanics**:
  1. Confirm the value's computation does not depend on the calling context or other parameters.
  2. Extract the computation into its own method if it is more than a call.
  3. Replace uses of the parameter inside the method with that call.
  4. Remove the now-unused parameter and clean up the call sites.
- **Benefits**: Simpler calls and no speculative parameters. **Drawbacks**: If callers later need to vary the value, the parameter has to come back.
- **Fixes smells**: [Long Parameter List](code-smells.md#long-parameter-list)

### Introduce Parameter Object

- **Problem**: The same group of parameters recurs across several method signatures.
- **Solution**: Replace the group with a single object carrying those values.
- **Why**: Names the concept the parameters collectively represent, and gives its logic a home.
- **Mechanics**:
  1. Create a class, preferably immutable, for the parameter group.
  2. Add it as a new parameter to the method.
  3. Update callers to construct and pass it.
  4. Delete the old parameters one at a time, reading fields from the object instead.
  5. Test after each removal.
  6. Look for behaviour operating on the group and move it into the new class.
- **Benefits**: Shorter signatures and a named domain concept. **Drawbacks**: Left behaviour-free, the new class is itself a Data Class.
- **Fixes smells**: [Long Parameter List](code-smells.md#long-parameter-list), [Data Clumps](code-smells.md#data-clumps), [Primitive Obsession](code-smells.md#primitive-obsession), [Long Method](code-smells.md#long-method)

### Remove Setting Method

- **Problem**: A field must not change after construction, yet a setter exists for it.
- **Solution**: Delete the setter and set the value in the constructor.
- **Why**: A public setter advertises mutability the design does not actually permit.
- **Mechanics**:
  1. Make sure the constructor accepts the field's value.
  2. Find every setter call.
  3. Fold each one into the corresponding construction call.
  4. Replace setter use inside constructors with direct field assignment.
  5. Delete the setter.
- **Benefits**: Immutability enforced by the type, not by convention. **Drawbacks**: Every existing setter call must be migrated.
- **Fixes smells**: —

### Hide Method

- **Problem**: A method is public but nothing outside the class or hierarchy calls it.
- **Solution**: Reduce its visibility to private or protected.
- **Why**: A smaller public surface is a smaller commitment to keep.
- **Mechanics**:
  1. Confirm with static analysis and tests that no external caller exists.
  2. Lower the visibility a step at a time, recompiling after each.
  3. Where an accessor was only used internally, use the field directly.
  4. Stop at the tightest visibility that still compiles and passes tests.
- **Benefits**: A public interface that says what the class is for. **Drawbacks**: None of note.
- **Fixes smells**: [Data Class](code-smells.md#data-class)

### Replace Constructor with Factory Method

- **Problem**: A constructor does more than assign fields, or must choose what to build.
- **Solution**: Create a static factory method that constructs and returns the object.
- **Why**: A factory can pick a subclass, reuse an instance, or carry a descriptive name — a constructor can do none of these.
- **Mechanics**:
  1. Add a static factory method that calls the existing constructor.
  2. Repoint every construction site at the factory.
  3. Make the constructor private.
  4. Move the non-assignment logic out of the constructor into the factory.
- **Benefits**: Named creation, polymorphic results, and the option of caching. **Drawbacks**: None of note.
- **Fixes smells**: —

### Replace Error Code with Exception

- **Problem**: A method signals failure by returning a special value the caller must remember to check.
- **Solution**: Throw an exception instead.
- **Why**: An unchecked error code is silently ignorable; an exception is not.
- **Mechanics**:
  1. Find every call site that inspects the error code.
  2. Decide whether the condition is checked or unchecked, and define the exception type.
  3. Throw the exception at the failure point instead of returning the code.
  4. Convert each caller's error-code branch into a catch, or let it propagate.
  5. Document the exception on the method.
- **Benefits**: Normal path free of error branches; failure handling lives in one place. **Drawbacks**: Do not use exceptions for conditions that are expected rather than exceptional.
- **Fixes smells**: —

### Replace Exception with Test

- **Problem**: An exception is used to handle a condition the caller could simply have checked.
- **Solution**: Test for the condition beforehand and handle it normally.
- **Why**: Exceptions are for the unexpected; using them for routine cases hides intent and costs performance.
- **Mechanics**:
  1. Write a conditional covering the edge case.
  2. Place it before the try block.
  3. Move the catch block's handling into that conditional.
  4. Make the catch block raise instead, to prove it is unreachable.
  5. Run the tests.
  6. Remove the try/catch once no exception occurs.
- **Benefits**: Clearer, cheaper handling of expected cases. **Drawbacks**: None of note, provided the check is genuinely reliable.
- **Fixes smells**: —

## Dealing with Generalization

### Pull Up Field

- **Problem**: Two or more subclasses declare the same field.
- **Solution**: Move it to their common superclass.
- **Why**: Subclasses written in parallel end up duplicating state that belongs one level up.
- **Mechanics**:
  1. Confirm the fields really mean the same thing in every subclass.
  2. Give them a common name if they differ, updating all references.
  3. Declare the field in the superclass with visibility the subclasses can use.
  4. Delete it from each subclass.
  5. Consider self-encapsulating it so subclasses go through accessors.
- **Benefits**: State declared once; unblocks pulling up the methods that use it. **Drawbacks**: None of note.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code)

### Pull Up Method

- **Problem**: Subclasses contain methods that do the same thing.
- **Solution**: Move one copy into the superclass and delete the rest.
- **Why**: Shared behaviour maintained in several places drifts apart and gets fixed unevenly.
- **Mechanics**:
  1. Compare the implementations and make them identical.
  2. Align signatures on the version the superclass will hold.
  3. Move the method up, resolving subclass-specific references via accessors or new abstract methods.
  4. Delete the subclass copies.
  5. Update callers to use the superclass type where they can.
- **Benefits**: One place to read and change the behaviour. **Drawbacks**: Subclass-specific dependencies may force extra abstract methods.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code)

### Pull Up Constructor Body

- **Problem**: Subclass constructors begin with the same initialization code.
- **Solution**: Move that code to a superclass constructor the subclasses call.
- **Why**: Shared setup should be defined once, like any other shared behaviour.
- **Mechanics**:
  1. Create a constructor on the superclass.
  2. Move the common leading initialization into it, taking the values it needs as parameters.
  3. Call the superclass constructor first thing in each subclass constructor and delete the moved lines.
- **Benefits**: Initialization logic maintained in one place. **Drawbacks**: Most languages require the super call first, so only leading common code can move.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code)

### Push Down Method

- **Problem**: A superclass method is relevant to only some of its subclasses.
- **Solution**: Move it down into the subclasses that use it.
- **Why**: A method most subclasses do not want makes the inherited interface a lie.
- **Mechanics**:
  1. Copy the method into each subclass that needs it.
  2. Delete it from the superclass.
  3. Confirm every caller works through a subclass reference, adjusting types where needed.
  4. If several but not all subclasses need it, introduce an intermediate superclass for them instead.
- **Benefits**: The superclass interface reflects what all subclasses actually do. **Drawbacks**: Copying to many subclasses reintroduces duplication.
- **Fixes smells**: [Refused Bequest](code-smells.md#refused-bequest)

### Push Down Field

- **Problem**: A superclass field is used by only some subclasses.
- **Solution**: Declare it in those subclasses instead.
- **Why**: Fields nobody else uses clutter the base class and mislead about shared state.
- **Mechanics**:
  1. Verify which subclasses actually read or write the field.
  2. Declare it in each of those subclasses.
  3. Remove it from the superclass.
  4. Fix any superclass code that referenced it, moving that code down as well.
- **Benefits**: State sits where it is used. **Drawbacks**: Pushing into many subclasses duplicates the field — only worth it when they use it differently.
- **Fixes smells**: [Refused Bequest](code-smells.md#refused-bequest)

### Extract Subclass

- **Problem**: A class has features used only in certain cases.
- **Solution**: Move those features into a subclass used only in those cases.
- **Why**: Special-case behaviour need not burden every instance, but is too small to justify a wholly separate class.
- **Mechanics**:
  1. Create a subclass of the original class.
  2. Give it a constructor taking any data the special case needs.
  3. Construct the subclass at the call sites that need the special behaviour.
  4. Push the special-case methods and then fields down into it.
  5. Delete the flag fields that used to select the behaviour.
  6. Replace the remaining flag conditionals with polymorphism.
- **Benefits**: Special cases separated cleanly with no new top-level class. **Drawbacks**: Inheritance handles only one axis of variation — use composition or a strategy for several.
- **Fixes smells**: [Large Class](code-smells.md#large-class)

### Extract Superclass

- **Problem**: Two classes have fields and methods in common.
- **Solution**: Create a shared superclass and move the common parts into it.
- **Why**: Inheritance is the direct way to state and reuse what two classes genuinely share.
- **Mechanics**:
  1. Create an abstract superclass and make both classes extend it.
  2. Pull up the common fields.
  3. Pull up the common methods, aligning them first if they differ.
  4. Pull up shared constructor logic.
  5. Retype clients to the superclass wherever they do not need a specific subclass.
- **Benefits**: Duplication eliminated and the shared concept named. **Drawbacks**: Unavailable when the classes already extend something else.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code)

### Extract Interface

- **Problem**: Several classes offer the same set of operations, or several clients use the same subset of one class.
- **Solution**: Declare that subset as an interface the classes implement.
- **Why**: Names the role being played and lets any implementation be substituted for another.
- **Mechanics**:
  1. Create an empty interface.
  2. Declare the shared operations on it.
  3. Mark the relevant classes as implementing it.
  4. Change client declarations to the interface type.
- **Benefits**: Explicit contracts and substitutable implementations. **Drawbacks**: Removes no duplication by itself — pair with Extract Class or Extract Superclass for that.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code), [Alternative Classes with Different Interfaces](code-smells.md#alternative-classes-with-different-interfaces)

### Collapse Hierarchy

- **Problem**: A subclass and its superclass have become effectively the same.
- **Solution**: Merge them into one class.
- **Why**: A level of hierarchy that distinguishes nothing costs navigation for no benefit.
- **Mechanics**:
  1. Choose which of the two classes survives.
  2. Move the members across with Pull Up or Push Down as appropriate.
  3. Repoint every reference at the surviving class.
  4. Delete the empty class.
- **Benefits**: A shallower, easier hierarchy. **Drawbacks**: With other subclasses present, collapsing the wrong one can break substitutability.
- **Fixes smells**: [Lazy Class](code-smells.md#lazy-class), [Speculative Generality](code-smells.md#speculative-generality)

### Form Template Method

- **Problem**: Subclasses implement the same algorithm, differing only in some steps.
- **Solution**: Put the algorithm's skeleton in the superclass and leave the varying steps abstract.
- **Why**: When the sequence itself is duplicated, changing it means editing every subclass.
- **Mechanics**:
  1. Break each subclass's algorithm into one method per step.
  2. Pull up the steps that are identical.
  3. Give differing steps the same names and signatures across subclasses.
  4. Declare those steps abstract in the superclass, leaving the bodies below.
  5. Pull up the top-level method that calls the steps in order.
- **Benefits**: The sequence is defined once; new variants only implement the steps. **Drawbacks**: None of note, though deep step hierarchies can be hard to trace.
- **Fixes smells**: [Duplicate Code](code-smells.md#duplicate-code)

### Replace Inheritance with Delegation

- **Problem**: A subclass uses only part of its superclass, or the inheritance does not express a real is-a relationship.
- **Solution**: Hold an instance of the former superclass in a field and forward only what is needed.
- **Why**: Inheritance used purely for reuse leaks unwanted methods into the subclass's interface.
- **Mechanics**:
  1. Add a field to the subclass holding an instance of the superclass.
  2. Rewrite the subclass's methods to work through that field.
  3. Add forwarding methods for the inherited operations clients genuinely use.
  4. Remove the inheritance declaration.
  5. Initialize the field, typically in the constructor.
- **Benefits**: A minimal, honest interface and the freedom to swap the delegate. **Drawbacks**: You must write and maintain the delegating methods.
- **Fixes smells**: [Refused Bequest](code-smells.md#refused-bequest)

### Replace Delegation with Inheritance

- **Problem**: A class delegates nearly the whole public interface of another class.
- **Solution**: Inherit from that class and delete the forwarding methods.
- **Why**: Once delegation covers everything, it is pure boilerplate that inheritance provides for free.
- **Mechanics**:
  1. Make the class a subclass of the delegate's class.
  2. Keep the delegate field pointing at the object for now.
  3. Delete the delegating methods one at a time, renaming as needed to match.
  4. Replace uses of the delegate field with references to the object itself.
  5. Remove the field.
- **Benefits**: Much less code for the same behaviour. **Drawbacks**: Wrong when only part of the interface is delegated — that breaks substitutability — and impossible if the class already has a superclass.
- **Fixes smells**: [Inappropriate Intimacy](code-smells.md#inappropriate-intimacy)
