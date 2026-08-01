# Grim Dawn — Damage & Defense Model

> Reference for the suggestion engine's reasoning about **item and skill interactions**.
> Compiled from the official combat guide + Game Mechanics wiki and corroborating
> community references (sources at the end). Where a value couldn't be verified it is
> marked **(verify)** rather than guessed — per project rule
> [[derive-facts-from-data-never-invent]]: state mechanics from sources/data, not memory.

This is the *rules* layer. The *numbers* (a skill's flat damage, an item's % bonus)
come from the datamined KB (`data/kb/*.json`). Together they let the engine explain
*why* a piece of gear or a skill point helps a build.

---

## 1. Offense: how a hit's damage is built

Order of operations for a single attack/skill instance:

1. **Base damage** of the skill (or the weapon, for weapon attacks).
2. **Flat / added damage** — applies to **weapon attacks only**, and to skills that
   deal **% Weapon Damage (%WD)**. Flat damage does **not** boost a skill's own
   non-weapon damage. A %WD skill takes everything a normal weapon swing would do
   (flat damage, life steal, on-hit procs) and multiplies it by the listed %.
3. **Damage conversion** (see §2).
4. **% damage bonuses** — apply to **all** damage of that type (skills *and* weapon
   attacks). **% bonuses stack additively**: +50% Fire from gear and +50% from an
   aura = +100% Fire, not ×2.25.
5. **Offensive ability / crit** roll (see §3) scales the final number.

**Engine implications**
- Flat damage only matters for weapon-based (%WD) builds; a caster skill gains
  nothing from "+X flat fire" unless it has %WD.
- Because % bonuses are additive, the *marginal* value of more % falls as totals
  rise (~1500–2000%+); past that, **flat damage** and **resist reduction** give more.
- "+skills" that raise a skill's %WD or flat scaling are multiplicative with the
  weapon; very strong for weapon builds.

## 2. Damage conversion (converted once, order matters)

Conversion order (each type is converted **at most once**):

1. Base skill
2. Skill modifiers
3. Conversion on modifiers / transmuter
4. **Global** conversion (equipment & buffs)
5. **% damage** on equipment/auras/passives — applied **after** conversion, to the
   *final* type.

- Multiple conversions **at the same step** are additive and pro-rata'd to 100%
  (e.g. two 50% global conversions of the same source split it).
- Once converted, damage can't be converted again (physical→chaos won't then →
  lightning).

**Engine implications**
- Conversion items are build-defining: converting a skill's damage to your build's
  type lets all your +% and RR for that type apply. Suggesting the *right* conversion
  source is high-value. Order (skill/transmuter vs global) determines what stacks.

## 3. Offensive Ability, hit chance & crits

Chance-to-hit (**PTH**) from attacker OA vs defender DA:

```
PTH = ( (OA / ((DA/3.5) + OA)) * 300 ) * 0.3
    + ( (((OA*3.25) + 10000) - (DA*3.25)) / 100 ) * 0.7
    - 50
```

- Equal OA and DA → **90% PTH** and **0% crit**.
- **Crit chance = PTH − 90** (95 PTH → 5% crit; 110 PTH → 20% crit).
- **Low-PTH penalty:** if PTH < 75, landed hits do `PTH/75` of normal damage
  (PTH 70 → 93.3%).
- **Crit damage** scales up as OA exceeds DA, in tiers, up to a max of **×3.5**
  (needs large OA lead / over-levelling). Exact per-tier breakpoints **(verify)**.

**Engine implications**
- OA is dual-purpose: hit chance *and* crit chance/damage. For crit builds, OA is a
  primary stat to push; the engine should value +OA and %crit-damage gear.
- DoTs lock their crit at application (see §4), so OA timing matters for DoT builds.

## 4. Damage over time (DoT)

- **Same-source** DoT: only the **highest** active instance ticks; weaker instances
  pause (still counting down) and resume if they outlast the top one. Re-applying the
  **same** DoT does **not** add damage — it **refreshes duration**.
- **Different sources** stack and each does full damage.
- **Crit is locked at application**: if the applying hit crit, the whole DoT duration
  deals crit damage. DoT ticks themselves **don't proc** anything.
- **+% Duration** adds extra ticks at the current damage (100/s for 3s at +200%
  duration → 100/s for 9s), so duration ≈ a damage multiplier for DoT builds.

### 4.1 What counts as a "source" (double affixes)

- **All flat DoT damage on your gear is treated as weapon damage = one source.** So
  **two bleeding affixes on the same item — or bleed spread across many gear pieces —
  simply *sum* into your weapon's total flat bleed and apply as ONE bleed DoT.** They
  are additive (more damage), **not** two independently-stacking instances.
- **% Damage / % Duration** modifiers always add additively regardless of where they
  come from.
- **Separate, stacking instances** require **different sources**: distinct skills with
  innate DoT (e.g. Cadence's bleed + Blade Arc), **weapon procs** (Bloodsong,
  Venomlash), and **devotion procs** (Falcon, Unknown Soldier, Oleron) each count as
  their own source and stack.
- **Per-weapon nuance:** flat DoT from *components/augments* applies **per weapon**, so
  when **dual-wielding** each hand's flat DoT is its own application; global/skill/
  devotion flat DoT applies once.

**Engine implications**
- For DoT builds, +% damage and +% duration are both effectively damage. A "double
  bleed" item is a bigger *single* source, not extra stacks — the engine should not
  count it as multiple instances. Real DoT scaling comes from **breadth of distinct
  sources** (skills + weapon procs + devotion procs), so the engine should prefer
  adding new sources over re-stacking the same one.

## 5. Defense: resistances

- Each damage type has a **resistance %**; incoming damage of that type is reduced by
  your resist. Default **max resistance 80%** (some sources raise the cap).
- **Over-cap** resistance (beyond the max) is valuable because it offsets enemy
  **resistance reduction** (§6) — it isn't wasted.

## 6. Resistance Reduction (RR) — three categories

Applied to the *target's* resistance. Three categories with different stacking:

| Cat | Wording (examples) | Stacks? | Step |
|-----|--------------------|---------|------|
| **B** | `-X% Resistance` (on a debuff skill, **no duration**) | **Additive, stacks across sources** | 1st |
| **C** | `X% Reduced target's Resistances` (**has duration**) | Only the **single highest** applies | 2nd (multiplicative) |
| **A** | `X Reduced target's Resistances` (flat, **has duration**) | Only the **single highest** applies | 3rd (flat) |

**Application order: B → C → A.**

```
if base_resist >= B_total:   final = (base_resist - B_total) * (1 - C_max) - A_max
else:                        final = (base_resist - B_total) * (1 + C_max) - A_max
```

(The sign flip means once resist is already negative, the % category deepens the
penalty.) Resistances can go **below zero**, increasing damage taken by the target.

**Engine implications**
- RR is one of the biggest damage multipliers in the game and is easy to under-value
  from raw stats alone. The engine should recognise which of a build's skills/items
  provide which **category** — you want ideally one of each (a stacking B source +
  the best C + the best A). Two Category-A items don't stack (only the largest), so
  the engine should warn about redundant A/C sources.

## 7. Armor & physical mitigation

- **Armor protects Physical damage only.** For a hit, armor absorbs **70%**
  (default, × any *% Armor Absorption* bonus) of the portion of the hit **within** the
  armor's protection value; the other 30% of that portion **plus 100% of any damage
  above** the protection value gets through.
  - Example: protection 100, hit for 120 → 100 within (×30% through = 30) + 20 above
    (full) = **50 taken**.
- **Location-based:** each physical hit randomly targets a body area, using that
  piece's protection — so armor is effectively spread across slots.
- **Internal Trauma bypasses armor entirely.** It (and other Physical-family effects)
  is instead reduced by **Physical Resistance** (`defensivePhysical`), a distinct
  stat from armor. Bleeding/Pierce are their own resistances.
- **Damage Absorption** (e.g. Menhir's Bulwark, Inquisitor Seal) is a *separate*
  flat/% layer that reduces damage after resists — not the same as armor absorption.

**Engine implications**
- For a physical/2H build, armor + %Armor Absorption is the physical-mitigation lever;
  but against Internal Trauma the engine must point at **Physical Resistance**, not
  armor. Conflating them is a common mistake the engine should avoid.

---

## Damage-type families (for build reasoning)

Matches the KB's `data/damage.py` families:
- **Elemental** = Fire + Cold + Lightning (a single %Elemental bonus feeds all three).
- Each element has a DoT: **Fire→Burn**, **Cold→Frostburn**, **Lightning→Electrocute**.
- **Physical→Internal Trauma** (DoT), **Vitality→Vitality Decay** (DoT),
  **Pierce**/**Bleeding** are Physical-family but separate resistances.
- Confirmed against records: **Vitality damage = `offensiveLife*`**, Vitality Decay =
  `offensiveSlowLife*`, elements have `offensiveBase<Type>*` flat variants.

## Open items to verify later
- Exact **crit-damage tier** breakpoints (only the ×3.5 cap is confirmed).
- Precise interaction of **% Absorption** stacking and the default 70% across pieces.
- Pet damage inheritance rules (separate model; out of scope for now).

## Sources
- Official combat guide: https://www.grimdawn.com/guide/gameplay/combat/
- Game Mechanics (Official Grim Dawn Wiki): https://grimdawn.fandom.com/wiki/Game_Mechanics
- Defense Stats / Internal Trauma (wiki): https://grimdawn.fandom.com/wiki/Defense_Stats ,
  https://grimdawn.fandom.com/wiki/Internal_Trauma_Damage
- Resistance Reduction categories: https://game-rack.com/en/grim-dawn/systems/resistance-reduction ,
  Akbar7th RR guide: https://gamefaqs.gamespot.com/pc/671567-grim-dawn/faqs/78675
- Community mechanics guide (Steam): https://steamcommunity.com/sharedfiles/filedetails/?id=596728673
