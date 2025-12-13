# PWA App Icons

You need to create app icons for the PWA to work on all devices.

## Quick Option: Use a PWA Icon Generator

1. Go to https://www.pwabuilder.com/imageGenerator
2. Upload a square logo/icon (preferably 512x512px or larger)
   - Use the peanut emoji 🥜 or create a simple logo
   - Suggested: Orange background (#FF6B35) with white peanut icon
3. Download the generated icon pack
4. Place all the icons in this folder (`src/static/icons/`)

## Required Icon Sizes:

- icon-72x72.png
- icon-96x96.png
- icon-128x128.png
- icon-144x144.png
- icon-152x152.png (for iOS)
- icon-192x192.png (for iOS and Android)
- icon-384x384.png
- icon-512x512.png (maskable - main app icon)

## Manual Creation (if needed):

If you want to create manually:
1. Create a 512x512px image with:
   - Background: #FF6B35 (sunrise orange)
   - Icon: White peanut 🥜 or "P" letter
   - Simple, recognizable design
2. Use an online tool like https://realfavicongenerator.net/ to resize to all needed sizes
3. Save all sizes to this folder

## Design Tips:

- Keep it simple - it will be small on phones
- High contrast (orange + white works well)
- Avoid text (too small to read)
- Make it recognizable at tiny sizes
- The peanut emoji is perfect for this brand!
