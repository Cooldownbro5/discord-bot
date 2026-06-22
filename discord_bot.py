import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timedelta
import asyncio

# Set up bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Files for storage
DRAFT_FILE = 'draft_data.json'
REACTION_ROLES_FILE = 'reaction_roles.json'

# Global draft state
draft_state = {
    'active': False,
    'teams': [],
    'current_team_index': 0,
    'picks': [],  # List of {team, player, position}
    'available_players': [],
    'pick_deadline': None,
    'timer_task': None,
    'guild_id': None,
    'current_round': 1,
    'picks_this_round': 0,
    'timer_id': 0,  # Track which timer is current
    'results_message_id': None,  # Track draft results message
    'teams_message_id': None,  # Track team rosters message
    'draft_channel_id': None  # Channel for draft results
}

def load_draft_data():
    """Load draft data from JSON file"""
    if os.path.exists(DRAFT_FILE):
        with open(DRAFT_FILE, 'r') as f:
            return json.load(f)
    return {'teams': [], 'picks': []}

def save_draft_data(data):
    """Save draft data to JSON file"""
    with open(DRAFT_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def load_reaction_roles():
    """Load reaction roles from JSON file"""
    if os.path.exists(REACTION_ROLES_FILE):
        with open(REACTION_ROLES_FILE, 'r') as f:
            return json.load(f)
    return {}

def get_next_team_index():
    """Get the next team in snake draft order"""
    num_teams = len(draft_state['teams'])
    
    # Even rounds go reverse (2, 4, 6...), odd rounds go forward (1, 3, 5...)
    if draft_state['current_round'] % 2 == 0:
        # Reverse order
        return num_teams - 1 - draft_state['picks_this_round']
    else:
        # Forward order
        return draft_state['picks_this_round']

async def get_draft_channel(ctx):
    """Get the channel to send draft results to"""
    if draft_state['draft_channel_id']:
        try:
            return ctx.bot.get_channel(draft_state['draft_channel_id'])
        except:
            return ctx.channel
    return ctx.channel

def save_reaction_roles(data):
    """Save reaction roles to JSON file"""
    with open(REACTION_ROLES_FILE, 'w') as f:
        json.dump(data, f, indent=4)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print('------')

@bot.event
async def on_raw_reaction_add(payload):
    """Handle when someone reacts to a message"""
    reaction_roles = load_reaction_roles()
    
    # Create a key from message ID and emoji
    key = f"{payload.message_id}_{payload.emoji.name}"
    
    if key not in reaction_roles:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return
    
    role_id = reaction_roles[key]
    role = guild.get_role(role_id)
    
    if role:
        await member.add_roles(role)
        print(f"Added {role.name} to {member.name}")

@bot.event
async def on_raw_reaction_remove(payload):
    """Handle when someone removes a reaction"""
    reaction_roles = load_reaction_roles()
    
    # Create a key from message ID and emoji
    key = f"{payload.message_id}_{payload.emoji.name}"
    
    if key not in reaction_roles:
        return
    
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    
    member = guild.get_member(payload.user_id)
    if not member or member.bot:
        return
    
    role_id = reaction_roles[key]
    role = guild.get_role(role_id)
    
    if role:
        await member.remove_roles(role)
        print(f"Removed {role.name} from {member.name}")

# ============ REACTION ROLE COMMANDS ============

@bot.command(name='setrole')
@commands.has_permissions(administrator=True)
async def set_reaction_role(ctx, action: str = None, *args):
    """
    Set up a reaction role
    Usage: !setrole send [channel] [message] [emoji] [role]
    Example: !setrole send #roles "React for draftable role" 📋 @DRAFTABLE
    """
    
    if action is None or action.lower() != 'send':
        await ctx.send("❌ Usage: `!setrole send [channel] [message] [emoji] [role]`\nExample: `!setrole send #roles \"React for role\" 📋 @DRAFTABLE`")
        return
    
    if len(args) < 4:
        await ctx.send("❌ Usage: `!setrole send [channel] [message] [emoji] [role]`")
        return
    
    # Parse arguments
    channel_mention = args[0]
    message_text = args[1]
    emoji = args[2]
    role_mention = args[3]
    
    # Get channel
    if channel_mention.startswith('<#') and channel_mention.endswith('>'):
        channel_id = int(channel_mention.strip('<>#'))
        channel = ctx.bot.get_channel(channel_id)
    else:
        channel = discord.utils.get(ctx.guild.channels, name=channel_mention.strip('#'))
    
    if not channel:
        await ctx.send(f"❌ Channel {channel_mention} not found!")
        return
    
    # Get role
    if role_mention.startswith('<@&') and role_mention.endswith('>'):
        role_id = int(role_mention.strip('<@&>'))
        role = ctx.guild.get_role(role_id)
    else:
        role = discord.utils.get(ctx.guild.roles, name=role_mention.strip('@'))
    
    if not role:
        await ctx.send(f"❌ Role {role_mention} not found!")
        return
    
    # Send message to channel
    try:
        msg = await channel.send(message_text)
        await msg.add_reaction(emoji)
        
        # Save reaction role
        reaction_roles = load_reaction_roles()
        key = f"{msg.id}_{emoji}"
        reaction_roles[key] = role.id
        save_reaction_roles(reaction_roles)
        
        await ctx.send(f"✅ Sent message to {channel.mention} and set up reaction role: {emoji} → {role.mention}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

def has_leader_role():
    """Check if user has a leader role or admin perms"""
    async def predicate(ctx):
        # Check if admin
        if ctx.author.guild_permissions.administrator:
            return True
        
        # Check if has any leader role
        leader_roles = [role.name.lower() for role in ctx.author.roles if 'leader' in role.name.lower()]
        
        if not leader_roles:
            await ctx.send("❌ Only **leaders** and **admins** can use draft commands!")
            return False
        
        return True
    
    return commands.check(predicate)

# ============ DRAFT COMMANDS ============

@bot.command(name='draft')
@has_leader_role()
async def draft_command(ctx, action: str = None, *, args: str = None):
    """
    Draft system commands
    !draft start - Start a new draft
    !draft team [team_name] - Add a team to the draft
    !draft add [player_name] - Add a player to the available pool
    !draft pick [player_name] - Pick a player for your team
    !draft skip - Skip current team's pick
    !draft show - Show current draft chart
    !draft end - End the draft
    """
    
    if action is None:
        await ctx.send("❌ Use `!draft start`, `!draft team`, `!draft add`, `!draft pick`, `!draft show`, or `!draft end`")
        return
    
    action = action.lower()
    
    # ===== START DRAFT =====
    if action == 'start':
        if draft_state['active']:
            await ctx.send("❌ A draft is already in progress!")
            return
        
        draft_state['active'] = True
        draft_state['teams'] = []
        draft_state['picks'] = []
        draft_state['available_players'] = []
        draft_state['current_team_index'] = 0
        draft_state['current_round'] = 1
        draft_state['picks_this_round'] = 0
        draft_state['guild_id'] = ctx.guild.id
        draft_state['results_message_id'] = None
        draft_state['teams_message_id'] = None
        
        # Auto-set to draft-picks channel
        draft_picks_channel = discord.utils.get(ctx.guild.channels, name="draft-picks")
        if draft_picks_channel:
            draft_state['draft_channel_id'] = draft_picks_channel.id
            await ctx.send(f"🎯 **Draft started!** Results will be sent to #draft-picks\n\nUse `!draft team [team_name]` to add teams.")
        else:
            await ctx.send("❌ **#draft-picks** channel not found!\n\nCreate a channel called **draft-picks** or use `!draft setchannel [channel_name]`")
            draft_state['active'] = False
            return
        return
    
    # ===== SET DRAFT CHANNEL =====
    if action == 'setchannel':
        if not args:
            await ctx.send("❌ Usage: `!draft setchannel [channel_name]`\nExample: `!draft setchannel draft-results`")
            return
        
        channel_name = args.strip()
        channel = discord.utils.get(ctx.guild.channels, name=channel_name)
        
        if not channel:
            await ctx.send(f"❌ Channel **{channel_name}** not found!")
            return
        
        draft_state['draft_channel_id'] = channel.id
        await ctx.send(f"✅ Draft results will be sent to {channel.mention}")
        return
    
    # ===== ADD TEAM =====
    if action == 'team':
        if not draft_state['active']:
            await ctx.send("❌ No draft is active. Use `!draft start` first!")
            return
        
        if not args:
            await ctx.send("❌ Usage: `!draft team [team_name]`")
            return
        
        team_name = args.strip()
        if team_name in draft_state['teams']:
            await ctx.send(f"❌ Team **{team_name}** already exists!")
            return
        
        draft_state['teams'].append(team_name)
        await ctx.send(f"✅ Added team: **{team_name}**")
        
        if len(draft_state['teams']) > 1:
            await ctx.send(f"📊 Teams: {', '.join(draft_state['teams'])}\nUse `!draft add [player]` to add players to draft pool, then `!draft begin` to start picks!")
        return
    
    # ===== ADD PLAYER =====
    if action == 'add':
        if not draft_state['active']:
            await ctx.send("❌ No draft is active. Use `!draft start` first!")
            return
        
        if not args:
            await ctx.send("❌ Usage: `!draft add [player_name]`")
            return
        
        player_name = args.strip()
        if player_name in draft_state['available_players']:
            await ctx.send(f"❌ **{player_name}** is already in the pool!")
            return
        
        draft_state['available_players'].append(player_name)
        await ctx.send(f"✅ Added **{player_name}** to the draft pool")
        return
    
    # ===== BEGIN DRAFT PICKS =====
    if action == 'begin':
        if not draft_state['active']:
            await ctx.send("❌ No draft is active!")
            return
        
        if not draft_state['teams'] or len(draft_state['teams']) < 2:
            await ctx.send("❌ You need at least 2 teams!")
            return
        
        # Auto-load players with "draftable" role if none were manually added
        if not draft_state['available_players']:
            guild = ctx.guild
            # Search for draftable role (case-insensitive)
            draftable_role = None
            for role in guild.roles:
                if role.name.lower() == "draftable":
                    draftable_role = role
                    break
            
            if draftable_role:
                # Get all members with draftable role (use display_name for nicknames)
                draftable_members = [member.display_name for member in guild.members if draftable_role in member.roles]
                
                if not draftable_members:
                    await ctx.send("❌ No members found with the **draftable** role!")
                    return
                
                draft_state['available_players'] = draftable_members
                await ctx.send(f"✅ Loaded {len(draftable_members)} players with **draftable** role!")
            else:
                await ctx.send("❌ No **draftable** role found! Create it or manually add players with `!draft add [player]`")
                return
        
        draft_state['current_team_index'] = 0
        draft_state['picks_this_round'] = 0
        draft_state['results_message_id'] = None
        draft_state['teams_message_id'] = None
        current_team = draft_state['teams'][0]
        
        embed = discord.Embed(
            title="🎯 DRAFT STARTED!",
            description=f"**{current_team}** is picking first!\n\nWaiting for **{current_team} Leader** to use `!draft pick [player_name]`",
            color=discord.Color.gold()
        )
        embed.add_field(name="Available Players", value=", ".join(draft_state['available_players']), inline=False)
        embed.add_field(name="Time Limit", value="⏱️ 3 minutes per pick", inline=False)
        
        await ctx.send(embed=embed)
        
        # Start the timer
        draft_state['pick_deadline'] = datetime.now() + timedelta(minutes=3)
        await start_pick_timer(ctx)
        return
    
    # ===== MAKE A PICK =====
    if action == 'pick':
        if not draft_state['active']:
            await ctx.send("❌ No draft is active!")
            return
        
        if not args:
            await ctx.send("❌ Usage: `!draft pick [player_name]`")
            return
        
        # Get current team
        current_team = draft_state['teams'][draft_state['current_team_index']]
        
        # Check if user has the leader role for this team
        required_role_name = f"{current_team.lower()} leader"
        has_permission = any(role.name.lower() == required_role_name for role in ctx.author.roles)
        
        if not has_permission:
            await ctx.send(f"❌ Only **{current_team} Leader** can pick during **{current_team}**'s turn!")
            return
        
        player_name = args.strip()
        
        # Handle Discord mention format <@userid> or <@!userid>
        if player_name.startswith('<@') and player_name.endswith('>'):
            # Extract user ID from mention
            mention_id = player_name.strip('<@!>')
            try:
                # Get the member from the guild
                member = await ctx.guild.fetch_member(int(mention_id))
                actual_player_name = member.display_name
            except:
                await ctx.send(f"❌ Could not find user from mention!")
                return
        else:
            # Remove @ symbol if present (for manual typing)
            if player_name.startswith('@'):
                player_name = player_name[1:]
            
            # Find player with case-insensitive matching
            actual_player_name = None
            for available in draft_state['available_players']:
                if available.lower() == player_name.lower():
                    actual_player_name = available
                    break
        
        if not actual_player_name:
            await ctx.send(f"❌ **{player_name}** is not available or already picked!\n\n📋 Available: {', '.join(draft_state['available_players'][:5])}")
            return
        
        # Record the pick
        position = len(draft_state['picks']) + 1
        draft_state['picks'].append({
            'position': position,
            'team': current_team,
            'player': actual_player_name
        })
        
        draft_state['available_players'].remove(actual_player_name)
        
        await ctx.send(f"✅ **{current_team}** picked **{actual_player_name}** at position {position}!")
        
        # Give the drafted player the team role
        try:
            # Find the member by display name
            guild = ctx.guild
            member_to_role = None
            for member in guild.members:
                if member.display_name.lower() == actual_player_name.lower():
                    member_to_role = member
                    break
            
            if member_to_role:
                # Find the team role (e.g., "igloo" for "igloo" team)
                team_role = discord.utils.get(guild.roles, name=current_team.lower())
                if not team_role:
                    # Try to find case-insensitive
                    for role in guild.roles:
                        if role.name.lower() == current_team.lower():
                            team_role = role
                            break
                
                if team_role:
                    await member_to_role.add_roles(team_role)
                    await ctx.send(f"📋 Gave **{actual_player_name}** the **{current_team}** role!")
        except Exception as e:
            print(f"Error assigning role: {e}")
        
        # Show updated draft results
        embed = discord.Embed(title="📊 LIVE DRAFT RESULTS", color=discord.Color.purple())
        for pick in draft_state['picks']:
            embed.add_field(
                name=f"Pick #{pick['position']}",
                value=f"**{pick['team']}** → {pick['player']}",
                inline=False
            )
        
        # Get draft channel
        draft_channel = await get_draft_channel(ctx)
        
        # Update draft results message if it exists, otherwise send new one
        try:
            if draft_state['results_message_id']:
                msg = await draft_channel.fetch_message(draft_state['results_message_id'])
                await msg.edit(embed=embed)
            else:
                msg = await draft_channel.send(embed=embed)
                draft_state['results_message_id'] = msg.id
        except:
            msg = await draft_channel.send(embed=embed)
            draft_state['results_message_id'] = msg.id
        
        # Update team rosters
        team_rosters = {}
        for team in draft_state['teams']:
            team_rosters[team] = []
        
        for pick in draft_state['picks']:
            team_rosters[pick['team']].append(pick['player'])
        
        teams_embed = discord.Embed(title="👥 TEAM ROSTERS", color=discord.Color.green())
        
        for team in draft_state['teams']:
            players = team_rosters[team]
            if players:
                player_list = "\n".join([f"• {player}" for player in players])
                teams_embed.add_field(
                    name=f"{team} ({len(players)} picks)",
                    value=player_list,
                    inline=False
                )
            else:
                teams_embed.add_field(
                    name=f"{team} (0 picks)",
                    value="No picks yet",
                    inline=False
                )
        
        # Update team rosters message if it exists, otherwise send new one
        try:
            if draft_state['teams_message_id']:
                msg = await draft_channel.fetch_message(draft_state['teams_message_id'])
                await msg.edit(embed=teams_embed)
            else:
                msg = await draft_channel.send(embed=teams_embed)
                draft_state['teams_message_id'] = msg.id
        except:
            msg = await draft_channel.send(embed=teams_embed)
            draft_state['teams_message_id'] = msg.id
        
        # Move to next team in snake draft
        draft_state['picks_this_round'] += 1
        
        # Check if we completed a round
        if draft_state['picks_this_round'] >= len(draft_state['teams']):
            # Start new round
            draft_state['current_round'] += 1
            draft_state['picks_this_round'] = 0
        
        if draft_state['available_players']:
            # Get next team using snake draft logic
            next_team_index = get_next_team_index()
            draft_state['current_team_index'] = next_team_index
            next_team = draft_state['teams'][next_team_index]
            
            embed = discord.Embed(
                title="⏱️ Next Pick",
                description=f"**{next_team}** is now picking! (Round {draft_state['current_round']})\n\nWaiting for **{next_team} Leader**...",
                color=discord.Color.blue()
            )
            embed.add_field(name="Remaining Players", value=", ".join(draft_state['available_players'][:10]), inline=False)
            
            await ctx.send(embed=embed)
            
            # Reset timer
            draft_state['pick_deadline'] = datetime.now() + timedelta(minutes=3)
            await start_pick_timer(ctx)
        else:
            await ctx.send("🎉 **Draft Complete!** Use `!draft show` to see final results.")
            draft_state['active'] = False
        
        return
    
    # ===== SKIP TEAM =====
    if action == 'skip':
        if not draft_state['active']:
            await ctx.send("❌ No draft is active!")
            return
        
        current_team = draft_state['teams'][draft_state['current_team_index']]
        await ctx.send(f"⏭️ **{current_team}** was skipped!")
        
        # Move to next team in snake draft
        draft_state['picks_this_round'] += 1
        
        # Check if we completed a round
        if draft_state['picks_this_round'] >= len(draft_state['teams']):
            # Start new round
            draft_state['current_round'] += 1
            draft_state['picks_this_round'] = 0
        
        # Get next team using snake draft logic
        next_team_index = get_next_team_index()
        draft_state['current_team_index'] = next_team_index
        next_team = draft_state['teams'][next_team_index]
        
        await ctx.send(f"➡️ **{next_team}** is now picking! (Round {draft_state['current_round']})")
        draft_state['pick_deadline'] = datetime.now() + timedelta(minutes=3)
        await start_pick_timer(ctx)
        return
    
    # ===== SHOW DRAFT CHART =====
    if action == 'show':
        if not draft_state['picks']:
            await ctx.send("❌ No picks have been made yet!")
            return
        
        # Show all picks in order
        embed = discord.Embed(title="📊 DRAFT RESULTS (All Picks)", color=discord.Color.purple())
        
        for pick in draft_state['picks']:
            embed.add_field(
                name=f"Pick #{pick['position']}",
                value=f"**{pick['team']}** → {pick['player']}",
                inline=False
            )
        
        await ctx.send(embed=embed)
        return
    
    # ===== SHOW TEAM ROSTERS =====
    if action == 'teams':
        if not draft_state['picks']:
            await ctx.send("❌ No picks have been made yet!")
            return
        
        # Organize picks by team
        team_rosters = {}
        for team in draft_state['teams']:
            team_rosters[team] = []
        
        for pick in draft_state['picks']:
            team_rosters[pick['team']].append(pick['player'])
        
        # Create embed showing team rosters
        embed = discord.Embed(title="👥 TEAM ROSTERS", color=discord.Color.green())
        
        for team in draft_state['teams']:
            players = team_rosters[team]
            if players:
                player_list = "\n".join([f"• {player}" for player in players])
                embed.add_field(
                    name=f"{team} ({len(players)} picks)",
                    value=player_list,
                    inline=False
                )
            else:
                embed.add_field(
                    name=f"{team} (0 picks)",
                    value="No picks yet",
                    inline=False
                )
        
        await ctx.send(embed=embed)
        return
    
    # ===== END DRAFT =====
    if action == 'end':
        if not draft_state['active']:
            await ctx.send("❌ No draft is active!")
            return
        
        draft_state['active'] = False
        await ctx.send("🛑 Draft ended.")
        return
    
    await ctx.send("❌ Unknown command. Use `!draft show` for help.")

async def start_pick_timer(ctx):
    """Start a 3-minute timer for the current pick"""
    # Increment timer ID so old timers won't execute
    draft_state['timer_id'] += 1
    current_timer_id = draft_state['timer_id']
    
    await asyncio.sleep(180)  # 3 minutes
    
    # Only process if this is still the current timer and draft is active
    if draft_state['active'] and draft_state['timer_id'] == current_timer_id:
        current_team = draft_state['teams'][draft_state['current_team_index']]
        await ctx.send(f"⏰ **{current_team}**'s time is up! Skipping to next team...")
        
        # Move to next team in snake draft
        draft_state['picks_this_round'] += 1
        
        # Check if we completed a round
        if draft_state['picks_this_round'] >= len(draft_state['teams']):
            # Start new round
            draft_state['current_round'] += 1
            draft_state['picks_this_round'] = 0
        
        # Get next team using snake draft logic
        next_team_index = get_next_team_index()
        draft_state['current_team_index'] = next_team_index
        next_team = draft_state['teams'][next_team_index]
        
        await ctx.send(f"➡️ **{next_team}** is now picking! (Round {draft_state['current_round']})")
        draft_state['pick_deadline'] = datetime.now() + timedelta(minutes=3)
        await start_pick_timer(ctx)

@bot.command(name='bothelp')
async def help_command(ctx):
    """Show all available commands"""
    help_text = """
**Discord Bot Commands:**

**React Roles (Admin Only):**
`!setrole <message_id> <emoji> <@role>` - Set up a reaction role

**Draft System:**
`!draft setchannel [channel_name]` - Set where draft results are posted
`!draft start` - Start a new draft
`!draft team [name]` - Add a team to the draft
`!draft add [player]` - (Optional) Manually add a player to the draft pool
`!draft begin` - Begin the draft (auto-loads players with "draftable" role)
`!draft pick [player]` - Pick a player for your team
`!draft skip` - Skip current team's pick
`!draft show` - Show all picks in order
`!draft teams` - Show each team's roster
`!draft end` - End the draft
    """
    await ctx.send(help_text)

# Run the bot
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    
    # Load environment variables from .env file
    load_dotenv()
    TOKEN = os.getenv('DISCORD_TOKEN')
    
    if not TOKEN:
        print("❌ Error: DISCORD_TOKEN not found in .env file!")
        print("Create a .env file with: DISCORD_TOKEN=your_token_here")
    else:
        bot.run(TOKEN)
