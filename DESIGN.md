---
name: Precision Utility
colors:
  surface: '#f7f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f7f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#3c4a42'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#6c7a71'
  outline-variant: '#bbcabf'
  surface-tint: '#006c49'
  primary: '#006c49'
  on-primary: '#ffffff'
  primary-container: '#10b981'
  on-primary-container: '#00422b'
  inverse-primary: '#4edea3'
  secondary: '#712ae2'
  on-secondary: '#ffffff'
  secondary-container: '#8a4cfc'
  on-secondary-container: '#fffbff'
  tertiary: '#855300'
  on-tertiary: '#ffffff'
  tertiary-container: '#e29100'
  on-tertiary-container: '#523200'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#6ffbbe'
  primary-fixed-dim: '#4edea3'
  on-primary-fixed: '#002113'
  on-primary-fixed-variant: '#005236'
  secondary-fixed: '#eaddff'
  secondary-fixed-dim: '#d2bbff'
  on-secondary-fixed: '#25005a'
  on-secondary-fixed-variant: '#5a00c6'
  tertiary-fixed: '#ffddb8'
  tertiary-fixed-dim: '#ffb95f'
  on-tertiary-fixed: '#2a1700'
  on-tertiary-fixed-variant: '#653e00'
  background: '#f7f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  display-lg:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  title-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.01em
  code-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 4px
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
  gutter: 16px
  margin-mobile: 16px
  margin-desktop: 32px
  max-content-width: 1440px
---

## Brand & Style

The brand personality of this design system is defined by efficiency, clinical precision, and high-performance utility. It is designed for professional data scientists and labeling specialists who require a low-fatigue environment for high-density tasks.

The visual style follows a **Corporate / Modern** aesthetic with a heavy focus on data-centricity. It prioritizes clarity through structured information hierarchy and functional use of color to indicate system status. In this light mode configuration, the interface provides a clean, high-clarity workspace that maximizes readability during daylight hours, maintaining a "pro-grade" feel that avoids decorative excess while ensuring a crisp, professional appearance.

## Colors

This design system utilizes a light-mode structured palette where color is applied with intentionality against clean, neutral surfaces:

- **Primary (Emerald Teal):** Used for core success actions and active navigation. In light mode, this provides a professional, calming signal that anchors the interface.
- **Secondary (Royal Purple):** Used for specialized tool selections, AI-assisted suggestions, and complex metadata categorization.
- **Tertiary (Amber):** Strictly for attention-required states, warnings, and pending reviews.
- **Neutral (Slate):** The foundation of the UI. Backgrounds use very light slate tones (#F8FAFC) to provide a bright, airy canvas, while surface containers use white or subtle grey tiers to establish depth and organization.

## Typography

The typography system relies exclusively on **Inter** to maintain a systematic, utilitarian feel. In the light theme, text weights are optimized for maximum contrast and sharpness against bright backgrounds.

- **Headlines:** Use tighter letter spacing and SemiBold weights to create a strong visual anchor for page sections.
- **Body:** Standardized at 14px for density, ensuring users can view more data on-screen without excessive scrolling.
- **Labels:** Used for metadata and chip text, utilizing Medium weights to remain legible at smaller scales.
- **Contrast:** High contrast between titles (600/700 weight) and body text (400 weight) is mandatory to help users scan complex information layouts.

## Layout & Spacing

This design system employs a **Fluid Grid** model with fixed maximum widths for content readability. 

- **Grid:** A 12-column system is used for desktop views. For the labeling workbench, a flexible 3-pane layout is recommended: Sidebar (Navigation/Tools), Main Stage (Data Canvas), and Inspector (Metadata/Properties).
- **Rhythm:** Spacing follows a strict 4px/8px base. All padding and margins must be multiples of 8px to ensure mathematical harmony and alignment across dense data tables.
- **Density:** Components use a "compact" spacing logic. Gutters are kept at 16px to allow for maximum horizontal real estate for data columns and image labeling canvases.

## Elevation & Depth

In light mode, hierarchy is established through **Tonal Layers** and subtle ambient shadows to define boundaries. Lighter surfaces represent the background, while slightly darker or tinted containers indicate depth.

- **Base Layer:** The light neutral slate background serves as the primary canvas.
- **Surface Layer:** White or elevated light slate tones are used for cards and primary containers to create a distinct separation from the base.
- **Shadows:** 
    - *Shadow-SM:* Used for standard cards to provide a soft lift from the background.
    - *Shadow-MD:* Used for active states, modals, and dropdowns to suggest higher interactivity.
- **Outlines:** Subtle 1px borders are used in conjunction with shadows to maintain structure and prevent the UI from feeling "washed out" in high-brightness environments.

## Shapes

The shape language balances modern softness with professional structure. 

- **Primary Radius:** A 16px (1rem) radius is the standard for cards and main containers, providing a defined frame for technical data.
- **Component Radius:** Buttons, inputs, and small UI controls use an 8px (0.5rem) radius to maintain a more precise, functional appearance.
- **Consistency:** All interactive elements must maintain these radii to prevent the UI from feeling disjointed between the "macro" (containers) and "micro" (controls) levels.

## Components

### Buttons
- **Primary:** Emerald Teal background with White text. Bold and authoritative for "Submit" or "Complete" actions.
- **Secondary:** Royal Purple background with White text. Used for "Add Label" or "AI Suggest" actions.
- **Ghost:** Transparent background with subtle slate borders and text. Used for "Cancel" or "Reset" to keep the visual weight low.

### Cards
- Standard containers for data modules. Must include a 16px border-radius and a surface color that is distinct from the background. Headers within cards should be separated by a thin horizontal line.

### Input Fields & Selects
- 8px border-radius. Use a 1px border. On focus, the border should transition to Primary Emerald with a soft outer glow.

### Labels & Chips
- Used for classification tags. Chips should have a subtle background tint derived from the category color with high-contrast text to ensure legibility.

### Data Grid
- Rows should use alternating subtle background shades for readability. Hover states on rows should trigger a subtle primary highlight.