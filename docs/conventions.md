# Accessibility Identifier Conventions

Every UI element you want to **tap, assert on, or wait for** needs a stable
accessibility identifier. Maestro reads the platform a11y tree, so the
identifiers you set in code are exactly what `mobile-design-verify`'s tools
see.

## The `kind-noun-modifier` pattern

```
<kind>-<noun>[-<modifier>]
```

- **kind** — what role the element plays in the UI: `card`, `button`, `row`,
  `field`, `header`, `chip`, `tab`, `dialog`, `toast`, `link`.
- **noun** — what concept it represents in the domain: `todo`, `pet`,
  `setting`, `chart`.
- **modifier** — optional disambiguator: an index (`0`, `1`), a state
  (`active`, `selected`), a value (`luna`, `mochi`).

### Good

- `todo-card-0` — first todo card on the home screen
- `todo-detail-1` — detail screen for the second todo
- `todo-step-row-2` — third step in a detail screen
- `setting-toggle-notifications`
- `dialog-confirm-delete`
- `tab-account-active`

### Bad

- `card1` — no kind separator, hard to grep
- `MyCustomCardComponent` — implementation, not role
- `todoButton` — camelCase, harder to scan
- `theBigBlueButton` — describes appearance, not identity
- `tap-me` — describes behavior, not which element

### Why hyphens

- Easy to grep: `grep -r "todo-card-" .`
- No special handling in Maestro / Espresso / XCUITest selectors — passed as
  opaque strings.
- Aligns with HTML's `id` attribute convention.

## Per-platform code samples

### SwiftUI (iOS)

```swift
HStack {
    Image(systemName: "checkmark.circle.fill")
    Text("Buy groceries")
}
.accessibilityElement(children: .combine)
.accessibilityIdentifier("todo-card-0")
```

`.accessibilityElement(children: .combine)` merges child elements so the
parent has a single a11y node — needed when the row has multiple text/image
children that would otherwise show up as separate a11y elements at the leaf
level.

For navigation destinations, set the identifier on the destination's root
view, not the link:

```swift
NavigationLink {
    TodoDetailView(todo: todo)
        .accessibilityIdentifier("todo-detail-\(index)")
} label: {
    TodoCard(todo: todo)
        .accessibilityIdentifier("todo-card-\(index)")
}
```

### Flutter (Dart)

```dart
Semantics(
  identifier: 'todo-card-0',
  child: Card(
    child: ListTile(
      title: const Text('Buy groceries'),
      onTap: () { /* ... */ },
    ),
  ),
);
```

`Semantics(identifier: ...)` maps to:

- **iOS**: `accessibilityIdentifier` on the underlying `UIView`
- **Android**: `resource-id` (Flutter ≥ 3.10) — visible to Maestro

Verified working on Flutter 3.41.5 with the smoke tests.

For `TextField`s, put the identifier on the parent (or the field's
`InputDecoration` via `enableSuggestions: ...` parent), since the field
itself owns the focus:

```dart
Semantics(
  identifier: 'field-search-query',
  child: TextField(decoration: InputDecoration(hintText: 'Search')),
);
```

### Compose (Android Kotlin)

```kotlin
Card(
    modifier = Modifier
        .semantics { testTagsAsResourceId = true }   // ONCE at compose root
        .testTag("todo-card-0"),
) {
    ListItem(headlineContent = { Text("Buy groceries") })
}
```

> **Critical:** `testTag` is invisible to Maestro by default. You must set
> `Modifier.semantics { testTagsAsResourceId = true }` **at the Compose root**
> (e.g. on the top-level `Surface` in your `Activity`'s `setContent`). Without
> it, Maestro will not surface your `testTag` values as `resource-id`. See
> [platforms.md](platforms.md#android-compose--kotlin) for the full
> wire-up.

## When you can't add an id (text fallback)

Sometimes you can't add an identifier — third-party widget, dynamically-rendered
content, system dialogs:

```python
mcp__mobile-design-verify__tap(platform="android", text="Save")
```

Text matching is fragile — it breaks if you localize the app, change the copy,
or the same text appears in multiple places. **Prefer ids whenever possible.**

## Coordinate fallback (last resort)

When neither id nor unique text is available:

```python
mcp__mobile-design-verify__tap(platform="android", point="540, 1170")
```

Coordinates are device-pixel and screen-resolution-dependent — they break
across device sizes. Avoid for repeatable flows.

## Testing your identifiers

After adding identifiers, verify they reach Maestro:

```python
mcp__mobile-design-verify__view_hierarchy(platform="android")
```

Look for your `id` strings in the returned tree. If they're missing:

- Did you wire up the platform-specific opt-in? (Compose `testTagsAsResourceId`,
  Flutter `Semantics`, SwiftUI `.combine` where needed.)
- Is the element actually on screen? (Maestro's hierarchy reflects the
  current viewport.)
- Did you rebuild and reinstall after the change?
