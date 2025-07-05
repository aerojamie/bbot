import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import csv
from datetime import datetime, timezone as dt_timezone
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pytz import timezone, all_timezones

# RUN ------ git pull origin main

# === Load token ===
load_dotenv("token.env")
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# === Data Files ===
AUTHORIZED_USERS_FILE = "authorized_users.json"
DATA_FILE = "shared_budget.json"
REMINDERS_FILE = "reminders.json"
USER_TIMEZONES_FILE = "user_timezones.json"
USER_JOBS_FILE = "user_jobs.json" # New file for job data

# === File Initialization ===
def initialize_json_file(file_path, default_data):
    if not os.path.exists(file_path):
        with open(file_path, 'w') as f:
            json.dump(default_data, f, indent=4)

initialize_json_file(AUTHORIZED_USERS_FILE, [922857347494318100, 1121745421971238973])
initialize_json_file(DATA_FILE, [])
initialize_json_file(REMINDERS_FILE, [])
initialize_json_file(USER_TIMEZONES_FILE, {})
initialize_json_file(USER_JOBS_FILE, {}) # Initialize the new jobs file

# === Data Loading and Saving Functions ===
def load_json_data(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {} if file_path in [USER_TIMEZONES_FILE, USER_JOBS_FILE] else []

def save_json_data(file_path, data):
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=4)

# Helper functions for specific files
def load_auth_users(): return load_json_data(AUTHORIZED_USERS_FILE)
def save_auth_users(users): save_json_data(AUTHORIZED_USERS_FILE, users)
def load_data(): return load_json_data(DATA_FILE)
def save_data(data): save_json_data(DATA_FILE, data)
def load_reminders(): return load_json_data(REMINDERS_FILE)
def save_reminders(reminders): save_json_data(REMINDERS_FILE, reminders)
def load_user_timezones(): return load_json_data(USER_TIMEZONES_FILE)
def save_user_timezones(timezones): save_json_data(USER_TIMEZONES_FILE, timezones)
def load_user_jobs(): return load_json_data(USER_JOBS_FILE)
def save_user_jobs(jobs): save_json_data(USER_JOBS_FILE, jobs)


# === Discord setup ===
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)
scheduler = AsyncIOScheduler()

@bot.event
async def on_ready():
    print(f"\u2705 Logged in as {bot.user}.")
    try:
        synced = await bot.tree.sync()
        print(f"\u2705 Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"\u274C Failed to sync commands: {e}")
    scheduler.add_job(check_reminders, 'interval', minutes=1)
    scheduler.start()

async def check_reminders():
    now = datetime.now(dt_timezone.utc)
    reminders = load_reminders()
    updated_reminders = []
    for r in reminders:
        reminder_time = datetime.fromisoformat(r["time"])
        if now >= reminder_time:
            try:
                user = await bot.fetch_user(r["user_id"])
                reminder_msg = f"\u23F0 **Reminder from {r['author_name']}:** {r['message']}"
                await user.send(reminder_msg)
            except discord.NotFound:
                print(f"User with ID {r['user_id']} not found for reminder.")
        else:
            updated_reminders.append(r)
    save_reminders(updated_reminders)

@bot.tree.command(name="set_timezone", description="Set your local timezone to be used for reminders.")
@app_commands.describe(timezone_name="Your timezone (e.g., 'America/Los_Angeles', 'Europe/London').")
async def set_timezone(interaction: discord.Interaction, timezone_name: str):
    if timezone_name not in all_timezones:
        await interaction.response.send_message("\u274C Invalid timezone. Please use a valid TZ database name.", ephemeral=True)
        return

    user_timezones = load_user_timezones()
    user_timezones[str(interaction.user.id)] = timezone_name
    save_user_timezones(user_timezones)

    await interaction.response.send_message(f"\u2705 Your timezone has been set to **{timezone_name}**.", ephemeral=True)

# === UPDATED REMINDER COMMAND ===
@bot.tree.command(name="rm", description="Set a reminder for one or more users.")
@app_commands.describe(
    message="What you want to remind them of.",
    year="The year for the reminder (e.g., 2025).",
    day="The day for the reminder (1-31).",
    hour="The hour in 24-hour format (0-23).",
    minute="The minute (0-59).",
    user1="The primary user to remind.",
    user2="An optional second user to remind.",
    user3="An optional third user to remind.",
    month="The month for the reminder."
)
@app_commands.choices(month=[
    app_commands.Choice(name="January", value=1),
    app_commands.Choice(name="February", value=2),
    app_commands.Choice(name="March", value=3),
    app_commands.Choice(name="April", value=4),
    app_commands.Choice(name="May", value=5),
    app_commands.Choice(name="June", value=6),
    app_commands.Choice(name="July", value=7),
    app_commands.Choice(name="August", value=8),
    app_commands.Choice(name="September", value=9),
    app_commands.Choice(name="October", value=10),
    app_commands.Choice(name="November", value=11),
    app_commands.Choice(name="December", value=12),
])
async def remember(
    interaction: discord.Interaction, 
    message: str, 
    year: app_commands.Range[int, datetime.now().year, 3000],
    month: int,
    day: app_commands.Range[int, 1, 31],
    hour: app_commands.Range[int, 0, 23],
    minute: app_commands.Range[int, 0, 59],
    user1: discord.User, 
    user2: discord.User = None, 
    user3: discord.User = None
):
    # Check timezone of the person setting the reminder
    user_timezones = load_user_timezones()
    author_id_str = str(interaction.user.id)
    if author_id_str not in user_timezones:
        await interaction.response.send_message(
            "\u274C You must set your own timezone with `/set_timezone` before reminding others.", 
            ephemeral=True
        )
        return

    # Parse the time using the author's timezone
    tz_str = user_timezones[author_id_str]
    try:
        tz = timezone(tz_str)
        # Construct the datetime object from the new, separate inputs
        local_time = datetime(year, month, day, hour, minute)
        aware_time = tz.localize(local_time).astimezone(dt_timezone.utc)
        
        # Check if the chosen time is in the past
        if aware_time < datetime.now(dt_timezone.utc):
            await interaction.response.send_message("\u274C You can't set a reminder for a time in the past.", ephemeral=True)
            return
            
    except ValueError:
        # This catches invalid dates, e.g., February 30th.
        await interaction.response.send_message("\u274C The date you entered is invalid. Please check the day, month, and year.", ephemeral=True)
        return
    except Exception as e:
        print(f"Error creating reminder time: {e}") # Log error for debugging
        await interaction.response.send_message("\u274C An error occurred while processing the time.", ephemeral=True)
        return

    # Collect all mentioned users
    targets = [u for u in [user1, user2, user3] if u is not None]
    reminders = load_reminders()
    
    # Create a reminder for each target user
    for target_user in targets:
        reminder = {
            "user_id": target_user.id,
            "author_name": interaction.user.display_name,
            "message": message,
            "time": aware_time.isoformat()
        }
        reminders.append(reminder)

    save_reminders(reminders)
    
    # Use a Discord timestamp for a clean, auto-localizing confirmation message
    time_unix = int(aware_time.timestamp())
    target_mentions = ", ".join(t.mention for t in targets)
    await interaction.response.send_message(
        f"\u2705 Reminder set! I will remind {target_mentions} to **{message}** on <t:{time_unix}:F> (which is <t:{time_unix}:R>)."
    )

# === New Paycheck Estimator Commands ===
@bot.tree.command(name="setjob", description="Set your job title and hourly wage.")
@app_commands.describe(
    job_name="Your job title.",
    wage_per_hour="Your hourly wage (e.g., 15.50)."
)
async def setjob(interaction: discord.Interaction, job_name: str, wage_per_hour: float):
    if interaction.user.id not in load_auth_users():
        await interaction.response.send_message("\u274C You are not authorized to use this command.", ephemeral=True)
        return
    
    if wage_per_hour <= 0:
        await interaction.response.send_message("\u274C Wage must be a positive number.", ephemeral=True)
        return

    user_jobs = load_user_jobs()
    user_jobs[str(interaction.user.id)] = {
        "job_name": job_name,
        "wage_per_hour": wage_per_hour
    }
    save_user_jobs(user_jobs)

    await interaction.response.send_message(f"\u2705 Your job has been set to **{job_name}** with a wage of **${wage_per_hour:.2f}/hour**.")

@bot.tree.command(name="estimate", description="Estimate a user's paycheck based on hours worked.")
@app_commands.describe(
    user="The user whose paycheck you want to estimate.",
    hours_worked="The number of hours worked."
)
async def estimate(interaction: discord.Interaction, user: discord.User, hours_worked: float):
    if interaction.user.id not in load_auth_users():
        await interaction.response.send_message("\u274C You are not authorized to use this command.", ephemeral=True)
        return

    user_jobs = load_user_jobs()
    user_id_str = str(user.id)

    if user_id_str not in user_jobs:
        await interaction.response.send_message(f"\u274C **{user.display_name}** has not set a job yet. They can do so with `/setjob`.", ephemeral=True)
        return
        
    job_info = user_jobs[user_id_str]
    wage = job_info['wage_per_hour']
    
    gross_pay = wage * hours_worked
    # Simplified deduction model (e.g., 25% flat rate for taxes, etc.)
    # This can be made more complex later if needed.
    deductions = gross_pay * 0.25 
    net_pay = gross_pay - deductions

    embed = discord.Embed(
        title=f"Paycheck Estimate for {user.display_name}",
        description=f"Based on **{hours_worked} hours** worked at **${wage:.2f}/hour**.",
        color=discord.Color.green()
    )
    embed.add_field(name="Gross Pay", value=f"`${gross_pay:,.2f}`", inline=False)
    embed.add_field(name="Estimated Deductions (25%)", value=f"`-${deductions:,.2f}`", inline=False)
    embed.add_field(name="Estimated Net Pay", value=f"**`${net_pay:,.2f}`**", inline=False)
    embed.set_footer(text="Note: This is a rough estimate. Actual pay may vary.")

    await interaction.response.send_message(embed=embed)


# === Budget Bot Commands ===
@bot.tree.command(name="help", description="Displays a list of all available commands.")
async def help_command(interaction: discord.Interaction):
    help_text = (
        "**\U0001F4D6 Budget Bot Commands:**\n\n"
        "`/add type amount category description`\n"
        "➤ Adds a new income or expense transaction.\n\n"
        "`/edit id field new_value`\n"
        "➤ Edits a specific field of an existing transaction.\n\n"
        "`/search keyword`\n"
        "➤ Searches for transactions by description, category, or amount.\n\n"
        "`/list` – Shows the last 10 transactions.\n"
        "`/summary` – Provides a summary of income, expenses, and net balance.\n"
        "`/delete id` – Deletes a transaction by its ID.\n"
        "`/export` – Sends you a DM with the budget data in JSON and CSV formats.\n"
        "`/authorize @user` – Grants a user permission to use the bot.\n"
        "`/deauthorize @user` – Revokes a user's permission.\n\n"
        "**\u23F0 Reminder Commands:**\n"
        "`/set_timezone timezone_name` – **Set this first!** Saves your local timezone.\n"
        "`/rm @user(s) message year month day hour minute` – Sets a reminder for other people (or yourself!).\n\n"
        "**\U0001F4B5 Paycheck Estimator:**\n"
        "`/setjob job_name wage_per_hour` – Set your job and hourly wage.\n"
        "`/estimate @user hours_worked` – Estimate a user's paycheck."
    )
    await interaction.response.send_message(help_text, ephemeral=True)
    
@bot.tree.command(name="add", description="Add a new income or expense transaction.")
@app_commands.describe(
    trans_type="The type of transaction.",
    amount="The amount of the transaction.",
    category="The category for the transaction (e.g., Food, Rent).",
    description="A brief description of the transaction."
)
@app_commands.choices(trans_type=[
    app_commands.Choice(name="Income", value="income"),
    app_commands.Choice(name="Expense", value="expense"),
])
async def add(interaction: discord.Interaction, trans_type: str, amount: float, category: str, description: str):
    if interaction.user.id not in load_auth_users():
        await interaction.response.send_message("\u274C You are not authorized to use this command.", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("\u274C Amount must be a positive number.", ephemeral=True)
        return

    transactions = load_data()
    transaction_id = int(datetime.now().timestamp() * 1000)
    transaction = {
        "id": transaction_id,
        "date": datetime.now().isoformat(),
        "type": trans_type.lower(),
        "amount": amount,
        "category": category.capitalize(),
        "description": description,
        "author_id": interaction.user.id,
        "author_name": interaction.user.name
    }
    transactions.append(transaction)
    save_data(transactions)
    await interaction.response.send_message(f"\u2705 {trans_type.title()} of ${amount:.2f} added for '{description}'.\n\U0001F196 Transaction ID: `{transaction_id}`")

@bot.tree.command(name="edit", description="Edit an existing transaction.")
@app_commands.describe(
    trans_id="The ID of the transaction to edit.",
    field="The field you want to change.",
    new_value="The new value for the selected field."
)
@app_commands.choices(field=[
    app_commands.Choice(name="Amount", value="amount"),
    app_commands.Choice(name="Category", value="category"),
    app_commands.Choice(name="Description", value="description"),
    app_commands.Choice(name="Type", value="type"),
])
async def edit(interaction: discord.Interaction, trans_id: int, field: str, new_value: str):
    if interaction.user.id not in load_auth_users():
        await interaction.response.send_message("\u274C You are not authorized.", ephemeral=True)
        return

    transactions = load_data()
    found = False
    for t in transactions:
        if t['id'] == trans_id:
            if field == "amount":
                try:
                    t[field] = float(new_value)
                except ValueError:
                    await interaction.response.send_message("\u274C Invalid amount. Please enter a number.", ephemeral=True)
                    return
            else:
                t[field] = new_value
            found = True
            break
    
    if found:
        save_data(transactions)
        await interaction.response.send_message(f"\u2705 Transaction `{trans_id}` updated successfully.")
    else:
        await interaction.response.send_message("\u274C Transaction not found.", ephemeral=True)

@bot.tree.command(name="search", description="Search for transactions.")
@app_commands.describe(keyword="The keyword to search for in description, category, or amount.")
async def search(interaction: discord.Interaction, keyword: str):
    if interaction.user.id not in load_auth_users():
        await interaction.response.send_message("\u274C You are not authorized.", ephemeral=True)
        return

    keyword = keyword.lower()
    transactions = load_data()
    matches = [
        t for t in transactions if
        keyword in t['description'].lower() or
        keyword in t['category'].lower() or
        keyword in str(t['amount'])
    ]
    if not matches:
        await interaction.response.send_message("\U0001F50D No matches found.", ephemeral=True)
        return

    lines = []
    for t in matches[:10]:
        date_str = datetime.fromisoformat(t['date']).strftime('%Y-%m-%d')
        sign = "+" if t['type'] == 'income' else "-"
        lines.append(f"{sign} ${t['amount']:.2f} ({t['category']}) - {t['description']} [{t['id']}] on {date_str}")

    await interaction.response.send_message("**\U0001F50D Search Results:**\n" + "\n".join(lines))

@bot.tree.command(name="export", description="Export all transaction data to a file.")
async def export(interaction: discord.Interaction):
    if interaction.user.id not in load_auth_users():
        await interaction.response.send_message("\u274C You are not authorized.", ephemeral=True)
        return

    transactions = load_data()
    if not transactions:
        await interaction.response.send_message("\U0001F4ED No transactions to export.", ephemeral=True)
        return

    json_path = f"budget_export_{interaction.user.id}.json"
    csv_path = f"budget_export_{interaction.user.id}.csv"

    save_json_data(json_path, transactions)

    with open(csv_path, 'w', newline='') as cf:
        if transactions:
            writer = csv.DictWriter(cf, fieldnames=transactions[0].keys())
            writer.writeheader()
            writer.writerows(transactions)

    try:
        await interaction.user.send("\U0001F4C1 Here is your exported budget data:")
        await interaction.user.send(file=discord.File(json_path))
        await interaction.user.send(file=discord.File(csv_path))
        await interaction.response.send_message("✅ Exported data has been sent to your DMs.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I couldn't send you a DM. Please check your privacy settings.", ephemeral=True)
    finally:
        if os.path.exists(json_path):
            os.remove(json_path)
        if os.path.exists(csv_path):
            os.remove(csv_path)


@bot.tree.command(name="authorize", description="Authorize a user to use the bot.")
@app_commands.describe(user="The user to authorize.")
async def authorize(interaction: discord.Interaction, user: discord.User):
    auth_users = load_auth_users()
    if interaction.user.id not in auth_users:
        await interaction.response.send_message("\u274C You are not authorized to manage users.", ephemeral=True)
        return

    if user.id in auth_users:
        await interaction.response.send_message("\u2705 User is already authorized.", ephemeral=True)
    else:
        auth_users.append(user.id)
        save_auth_users(auth_users)
        await interaction.response.send_message(f"\u2705 Authorized {user.mention}.")

@bot.tree.command(name="deauthorize", description="Deauthorize a user from using the bot.")
@app_commands.describe(user="The user to deauthorize.")
async def deauthorize(interaction: discord.Interaction, user: discord.User):
    auth_users = load_auth_users()
    if interaction.user.id not in auth_users:
        await interaction.response.send_message("\u274C You are not authorized to manage users.", ephemeral=True)
        return

    if user.id in auth_users:
        auth_users.remove(user.id)
        save_auth_users(auth_users)
        await interaction.response.send_message(f"\u2705 Deauthorized {user.mention}.")
    else:
        await interaction.response.send_message("\u26A0\uFE0F That user isn't currently authorized.", ephemeral=True)

@bot.tree.command(name="list", description="List the 10 most recent transactions.")
async def list_transactions(interaction: discord.Interaction):
    if interaction.user.id not in load_auth_users():
        await interaction.response.send_message("\u274C You are not authorized.", ephemeral=True)
        return

    transactions = load_data()
    if not transactions:
        await interaction.response.send_message("\U0001F914 No transactions recorded yet.", ephemeral=True)
        return

    latest = sorted(transactions, key=lambda t: t['date'], reverse=True)[:10]
    lines = []
    for t in latest:
        date_str = datetime.fromisoformat(t['date']).strftime('%Y-%m-%d')
        sign = "+" if t['type'] == 'income' else "-"
        lines.append(f"{sign} ${t['amount']:.2f} ({t['category']}) - {t['description']} [{t['id']}] on {date_str}")

    await interaction.response.send_message("**Last 10 Transactions:**\n" + "\n".join(lines))

@bot.tree.command(name="summary", description="Show a summary of all income and expenses.")
async def summary(interaction: discord.Interaction):
    if interaction.user.id not in load_auth_users():
        await interaction.response.send_message("\u274C You are not authorized.", ephemeral=True)
        return

    transactions = load_data()
    income = sum(t['amount'] for t in transactions if t['type'] == 'income')
    expenses = sum(t['amount'] for t in transactions if t['type'] == 'expense')
    balance = income - expenses

    msg = (
        f"**\U0001F4B0 Financial Summary**\n"
        f"Total Income: `${income:,.2f}`\n"
        f"Total Expenses: `${expenses:,.2f}`\n"
        f"**Net Balance:** `${balance:,.2f}`"
    )
    await interaction.response.send_message(msg)

@bot.tree.command(name="delete", description="Delete a transaction by its ID.")
@app_commands.describe(transaction_id="The unique ID of the transaction to delete.")
async def delete(interaction: discord.Interaction, transaction_id: int):
    if interaction.user.id not in load_auth_users():
        await interaction.response.send_message("\u274C You are not authorized.", ephemeral=True)
        return

    transactions = load_data()
    original_count = len(transactions)
    new_data = [t for t in transactions if t.get('id') != transaction_id]
    
    if len(new_data) == original_count:
        await interaction.response.send_message("\u274C Transaction not found.", ephemeral=True)
    else:
        save_data(new_data)
        await interaction.response.send_message(f"\u2705 Transaction `{transaction_id}` has been deleted.")

# === Run Bot ===
if __name__ == "__main__":
    if BOT_TOKEN:
        bot.run(BOT_TOKEN)
    else:
        print("\u274C Discord bot token not found in token.env file.")
