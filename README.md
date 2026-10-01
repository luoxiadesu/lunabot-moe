# LunaBot

A multi-functional chatbot based on Nonebot2

Note: This project is for reference and learning purposes only, and is **not** a completely deployable application.

- There may be issues with the deployment steps.

- Missing configurations and data will not be provided.

### Deployment Steps

#### 1. Install Dependencies

- Install dependencies using `pip install -r requirements.txt` (Python >=3.10 is recommended)

- Install playwright browsers by running the command: ```playwright install```

- Install system emoji fonts if emojis fail to render for commands such as `/help`

- Run `python patch_pilmoji.py` with the bot's Python interpreter after installing
  or reinstalling dependencies. The pinned Pilmoji 2.0.0 needs this compatibility
  patch for emoji 2.x. The script also repairs the previous patch that matched
  English emoji names instead of Unicode characters. Restart the bot and its
  drawing workers after applying it.

- Pillow-based bot images use Pilmoji to fetch emoji images from the Google-style
  emoji CDN. Those images are not bundled with pip; installing an emoji font alone
  does not fix a broken Pilmoji matcher. Browser-rendered images such as `/help`
  use system fonts separately. Successful assets are cached in
  `data/utils/emoji_cache`; downloads time out after 3 seconds per source and try
  Google Noto Emoji as a fallback. A previously cached emoji works offline.

#### 2. Setup Configurations

- Copy the configuration from the `example_config` directory to the `config` directory and fill in the missing content as needed.

- Rename `.env.example` to `.env`.

- Find and place the missing data yourself


#### 3. Run the Bot

- Start the project using nonebot2 cli command: `nb run`.

- Send a message `@yourbot /enable` to enable the bot in the group.

- (Optional) Start the Sekai Deck Recommendation Service: [README.md](./src/services/deck_recommender/README.md)

