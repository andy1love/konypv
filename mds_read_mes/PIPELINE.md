■ 制作ぱいぷらいん


1　■ カメラ SD card to LaCie HDD & Resolve Import
Script: workflow_launcher.py
Use when: Starting your day with new footage
What happens:
• Selects user and optionally runs ingest
• Imports media into DaVinci Resolve
• Creates bins and timelines automatically
TUTORIAL:
https://www.dropbox.com/scl/fi/edit7o49ugklqdwmvta3y/workflow_launcher.mov?rlkey=b7nvcs1iy7jgabob85uzbxs11&dl=0


1.5　■ RESOLVE 基本操作
RESOLVE BASICS 15minute TUTORIAL:
https://www.dropbox.com/scl/fi/lemo6kxt5mhw4rncs68r0/resolve_basics.mov?rlkey=8tvfrfth60deidedl419pmunf&dl=0



2　■ Proxy (サイズ縮小版)　作成
Script: proxy_maker.py
Use when: After ingesting media, before editing
What happens:
• Creates 1920×1080 H.264 proxies
• Mirrors folder structure from media pool
• Skips existing up-to-date proxies
TUTORIAL:
https://www.dropbox.com/scl/fi/sf4sf8jumbddihlmne9oe/proxy_maker.mov?rlkey=277si9gtqibla4ogl1wiv3t7a&dl=0



3　■ 送信準備。Proxy をパッケージする
Script: proxy_packager.py
Use when: When ready to send proxies to 
What happens:
• Packages completed proxy folders
• Creates date-based delivery buckets
• Auto-opens Dropbox File Request URLs
TUTORIAL:
https://www.dropbox.com/scl/fi/hinpvwax2jwbllyv3qct7/proxy_packager.mov?rlkey=20g4pvj053o7u97a7olj2kicb&dl=0



4　■ 寮 HDD へ MEDIA を SYNC
Script: sync_pools.py
Use when: For backup or offline access
What happens:
• Syncs media/proxy pools to external drives
• Supports per-user destination drives
• Optional MP4 back-sync
TUTORIAL:
https://www.dropbox.com/scl/fi/zcvyyfjb0833ewxmzwm64/sync_pools.mov?rlkey=69q8d5gva00xq0ysixq6rslbo&dl=0


4　■ 寮 HDD へ TIMELINE(.DRT)を書き出し、寮で編集、そして、それをScreening Roomに戻す。
I don't know if this is the best workflow so I am not automating this yet.
Please take a look at this video and try this out and figure out what works best for you.
Suggestion TUTORIAL:
https://www.dropbox.com/scl/fi/fvnb9wjtu3cssmpko7g12/Export_Transfer_Timeline.mov?rlkey=wi37iwv7vnt8ja83iywq8bb9a&dl=0



5　■ SD Card ゴミ箱整理 (Verification & Wipe)
Script: wipe_sdcard.py
Use when: Handing off the camera to the next team
What happens:
• Verifies all files exist in media pool
• Offers to copy missing files to _orphan
• Safely wipes card after confirmation
TUTORIAL:
1 - https://www.dropbox.com/scl/fi/pnsix98swymbaox8djuce/wipe_sdcard.mov?rlkey=25osslabvxylz1d587v6331tj&dl=0
2 - https://www.dropbox.com/scl/fi/i9lwkxiuu7p64kixyygvt/wipe_sdcard2.mov?rlkey=bkf86qmvruamwhpi9dyxuewg1&dl=0



--------------------------------------------------------------------

📝 PDF Generation Instructions

Create a **one-page dual-font PDF** of the above information with these rules:

- **Fonts**:  
  • Japanese text → HeiseiKakuGo-W5 (clear Gothic).  
  • English text → Helvetica (clean and readable).  

- **Formatting**:  
  • Main title centered, slightly larger.  
  • Section headings start with a colored ■ marker (only the ■ is colored).  
  • Colors:  
    - Step 1 = green  
    - Step 1.5 = black  
    - Step 2 = blue  
    - Step 3 = purple  
    - Step 4 = yellow  
    - Step 4.5 = black  
    - Step 5 = red  
  • Script: lines → **bold**  
  • Use when: lines → *italic*  
  • What happens: → bold, with proper indented bullet list.  
  • Add subtle gray divider lines between steps.  

- **Links**:  
  • Show tutorial links as **human-readable filenames** (e.g., `workflow_launcher.mov`).  
  • Links should be **blue, underlined, and clickable**.  
  • Put a light gray background highlight behind links to make them look button-like.  

- **Layout**:  
  • Keep everything compact so it fits on a single page.  
  • Use light gray body text instead of pure black for readability.  
  • Maintain spacing for clear separation but don’t waste vertical space.  

--------------------------------------------------------------------