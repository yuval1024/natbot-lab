#!/usr/bin/env python3
#
# natbot.py
#
# natbot_extra: set ANTHROPIC_API_KEY, NATBOT_START_URL, NATBOT_FIXES (optional); task on stdin. See README.md.
#

from playwright.sync_api import sync_playwright
import time
from sys import argv, exit, platform
import anthropic  # EXTRA: was `import openai` (OpenAI Completions -> Anthropic Messages)
import os
import json  # EXTRA: transcript log
FIX = set(os.environ.get("NATBOT_FIXES", "").split(",")) | ({"coord"} if os.environ.get("NATBOT_VARIANT") == "coordfix" else set())  # EXTRA: optional fixes, e.g. NATBOT_FIXES=mem,stop

quiet = False
if len(argv) >= 2:
	if argv[1] == '-q' or argv[1] == '--quiet':
		quiet = True
		print(
			"Running in quiet mode (HTML and other content hidden); \n"
			+ "exercise caution when running suggested commands."
		)

prompt_template = """
You are an agent controlling a browser. You are given:

	(1) an objective that you are trying to achieve
	(2) the URL of your current web page
	(3) a simplified text description of what's visible in the browser window (more on that below)

You can issue these commands:
	SCROLL UP - scroll up one page
	SCROLL DOWN - scroll down one page
	CLICK X - click on a given element. You can only click on links, buttons, and inputs!
	TYPE X "TEXT" - type the specified text into the input with id X
	TYPESUBMIT X "TEXT" - same as TYPE above, except then it presses ENTER to submit the form
	ANSWER "TEXT" - stop: the objective is achieved; TEXT is your final answer (what you found, or "done")

The format of the browser content is highly simplified; all formatting elements are stripped.
Interactive elements such as links, inputs, buttons are represented like this:

		<link id=1>text</link>
		<button id=2>text</button>
		<input id=3>text</input>

Images are rendered as their alt text like this:

		<img id=4 alt=""/>

Based on your given objective, issue whatever command you believe will get you closest to achieving your goal.
You always start on Google; you should submit a search query to Google that will take you to the best page for
achieving your objective. And then interact with that page to achieve your objective.

If you find yourself on Google and there are no search results displayed yet, you should probably issue a command 
like "TYPESUBMIT 7 "search query"" to get to a more useful page.

Then, if you find yourself on a Google search results page, you might issue the command "CLICK 24" to click
on the first link in the search results. (If your previous command was a TYPESUBMIT your next command should
probably be a CLICK.)

Don't try to interact with elements that you can't see.

Here are some examples:

EXAMPLE 1:
==================================================
CURRENT BROWSER CONTENT:
------------------
<link id=1>About</link>
<link id=2>Store</link>
<link id=3>Gmail</link>
<link id=4>Images</link>
<link id=5>(Google apps)</link>
<link id=6>Sign in</link>
<img id=7 alt="(Google)"/>
<input id=8 alt="Search"></input>
<button id=9>(Search by voice)</button>
<button id=10>(Google Search)</button>
<button id=11>(I'm Feeling Lucky)</button>
<link id=12>Advertising</link>
<link id=13>Business</link>
<link id=14>How Search works</link>
<link id=15>Carbon neutral since 2007</link>
<link id=16>Privacy</link>
<link id=17>Terms</link>
<text id=18>Settings</text>
------------------
OBJECTIVE: Find a 2 bedroom house for sale in Anchorage AK for under $750k
CURRENT URL: https://www.google.com/
YOUR COMMAND: 
TYPESUBMIT 8 "anchorage redfin"
==================================================

EXAMPLE 2:
==================================================
CURRENT BROWSER CONTENT:
------------------
<link id=1>About</link>
<link id=2>Store</link>
<link id=3>Gmail</link>
<link id=4>Images</link>
<link id=5>(Google apps)</link>
<link id=6>Sign in</link>
<img id=7 alt="(Google)"/>
<input id=8 alt="Search"></input>
<button id=9>(Search by voice)</button>
<button id=10>(Google Search)</button>
<button id=11>(I'm Feeling Lucky)</button>
<link id=12>Advertising</link>
<link id=13>Business</link>
<link id=14>How Search works</link>
<link id=15>Carbon neutral since 2007</link>
<link id=16>Privacy</link>
<link id=17>Terms</link>
<text id=18>Settings</text>
------------------
OBJECTIVE: Make a reservation for 4 at Dorsia at 8pm
CURRENT URL: https://www.google.com/
YOUR COMMAND: 
TYPESUBMIT 8 "dorsia nyc opentable"
==================================================

EXAMPLE 3:
==================================================
CURRENT BROWSER CONTENT:
------------------
<button id=1>For Businesses</button>
<button id=2>Mobile</button>
<button id=3>Help</button>
<button id=4 alt="Language Picker">EN</button>
<link id=5>OpenTable logo</link>
<button id=6 alt ="search">Search</button>
<text id=7>Find your table for any occasion</text>
<button id=8>(Date selector)</button>
<text id=9>Sep 28, 2022</text>
<text id=10>7:00 PM</text>
<text id=11>2 people</text>
<input id=12 alt="Location, Restaurant, or Cuisine"></input> 
<button id=13>Let’s go</button>
<text id=14>It looks like you're in Peninsula. Not correct?</text> 
<button id=15>Get current location</button>
<button id=16>Next</button>
------------------
OBJECTIVE: Make a reservation for 4 for dinner at Dorsia in New York City at 8pm
CURRENT URL: https://www.opentable.com/
YOUR COMMAND: 
TYPESUBMIT 12 "dorsia new york city"
==================================================

The current browser content, objective, and current URL follow. Reply with your next command to the browser.

CURRENT BROWSER CONTENT:
------------------
$browser_content
------------------

OBJECTIVE: $objective
CURRENT URL: $url
PREVIOUS COMMAND: $previous_command
YOUR COMMAND:
"""

black_listed_elements = set(["html", "head", "title", "meta", "iframe", "body", "script", "style", "path", "svg", "br", "::marker",])

class Crawler:
	def __init__(self):
		self.browser = (
			sync_playwright()
			.start()
			.chromium.launch(
				headless=False,
			)
		)

		self.page = self.browser.new_page()
		self.page.set_viewport_size({"width": 1280, "height": 1080})

	def go_to_page(self, url):
		self.page.goto(url=url if "://" in url else "http://" + url)
		self.client = self.page.context.new_cdp_session(self.page)
		self.page_element_buffer = {}

	def scroll(self, direction):
		if direction == "up":
			self.page.evaluate(
				"(document.scrollingElement || document.body).scrollTop = (document.scrollingElement || document.body).scrollTop - window.innerHeight;"
			)
		elif direction == "down":
			self.page.evaluate(
				"(document.scrollingElement || document.body).scrollTop = (document.scrollingElement || document.body).scrollTop + window.innerHeight;"
			)

	def click(self, id):
		# Inject javascript into the page which removes the target= attribute from all links
		js = """
		links = document.getElementsByTagName("a");
		for (var i = 0; i < links.length; i++) {
			links[i].removeAttribute("target");
		}
		"""
		self.page.evaluate(js)

		element = self.page_element_buffer.get(int(id))
		if element:
			x = element.get("center_x")
			y = element.get("center_y")
			
			if "coord" in FIX:  #F:coord  document -> viewport coordinates
				x, y = x - self.page.evaluate("window.scrollX"), y - self.page.evaluate("window.scrollY")  #F:coord
			self.page.mouse.click(x, y)
		else:
			print("Could not find element")

	def type(self, id, text):
		self.click(id)
		self.page.keyboard.type(text)

	def enter(self):
		self.page.keyboard.press("Enter")

	def crawl(self):
		page = self.page
		page_element_buffer = self.page_element_buffer
		start = time.time()

		page_state_as_text = []

		device_pixel_ratio = page.evaluate("window.devicePixelRatio")
		if platform == "darwin" and device_pixel_ratio == 1:  # lies
			device_pixel_ratio = 2

		win_scroll_x 		= page.evaluate("window.scrollX")
		win_scroll_y 		= page.evaluate("window.scrollY")
		win_upper_bound 	= page.evaluate("window.pageYOffset")
		win_left_bound 		= page.evaluate("window.pageXOffset") 
		win_width 			= page.evaluate("window.screen.width")
		win_height 			= page.evaluate("window.screen.height")
		win_right_bound 	= win_left_bound + win_width
		win_lower_bound 	= win_upper_bound + win_height
		document_offset_height = page.evaluate("document.body.offsetHeight")
		document_scroll_height = page.evaluate("document.body.scrollHeight")

#		percentage_progress_start = (win_upper_bound / document_scroll_height) * 100
#		percentage_progress_end = (
#			(win_height + win_upper_bound) / document_scroll_height
#		) * 100
		percentage_progress_start = 1
		percentage_progress_end = 2

		page_state_as_text.append(
			{
				"x": 0,
				"y": 0,
				"text": "[scrollbar {:0.2f}-{:0.2f}%]".format(
					round(percentage_progress_start, 2), round(percentage_progress_end)
				),
			}
		)

		tree = self.client.send(
			"DOMSnapshot.captureSnapshot",
			{"computedStyles": [], "includeDOMRects": True, "includePaintOrder": True},
		)
		strings	 	= tree["strings"]
		document 	= tree["documents"][0]
		nodes 		= document["nodes"]
		backend_node_id = nodes["backendNodeId"]
		attributes 	= nodes["attributes"]
		node_value 	= nodes["nodeValue"]
		parent 		= nodes["parentIndex"]
		node_types 	= nodes["nodeType"]
		node_names 	= nodes["nodeName"]
		is_clickable = set(nodes["isClickable"]["index"])

		text_value 			= nodes["textValue"]
		text_value_index 	= text_value["index"]
		text_value_values 	= text_value["value"]

		input_value 		= nodes["inputValue"]
		input_value_index 	= input_value["index"]
		input_value_values 	= input_value["value"]

		input_checked 		= nodes["inputChecked"]
		layout 				= document["layout"]
		layout_node_index 	= layout["nodeIndex"]
		bounds 				= layout["bounds"]

		cursor = 0
		html_elements_text = []

		child_nodes = {}
		elements_in_view_port = []

		anchor_ancestry = {"-1": (False, None)}
		button_ancestry = {"-1": (False, None)}

		def convert_name(node_name, has_click_handler):
			if node_name == "a":
				return "link"
			if node_name == "input":
				return "input"
			if node_name == "img":
				return "img"
			if (
				node_name == "button" or has_click_handler
			):  # found pages that needed this quirk
				return "button"
			else:
				return "text"

		def find_attributes(attributes, keys):
			values = {}

			for [key_index, value_index] in zip(*(iter(attributes),) * 2):
				if value_index < 0:
					continue
				key = strings[key_index]
				value = strings[value_index]

				if key in keys:
					values[key] = value
					keys.remove(key)

					if not keys:
						return values

			return values

		def add_to_hash_tree(hash_tree, tag, node_id, node_name, parent_id):
			parent_id_str = str(parent_id)
			if not parent_id_str in hash_tree:
				parent_name = strings[node_names[parent_id]].lower()
				grand_parent_id = parent[parent_id]

				add_to_hash_tree(
					hash_tree, tag, parent_id, parent_name, grand_parent_id
				)

			is_parent_desc_anchor, anchor_id = hash_tree[parent_id_str]

			# even if the anchor is nested in another anchor, we set the "root" for all descendants to be ::Self
			if node_name == tag:
				value = (True, node_id)
			elif (
				is_parent_desc_anchor
			):  # reuse the parent's anchor_id (which could be much higher in the tree)
				value = (True, anchor_id)
			else:
				value = (
					False,
					None,
				)  # not a descendant of an anchor, most likely it will become text, an interactive element or discarded

			hash_tree[str(node_id)] = value

			return value

		for index, node_name_index in enumerate(node_names):
			node_parent = parent[index]
			node_name = strings[node_name_index].lower()

			is_ancestor_of_anchor, anchor_id = add_to_hash_tree(
				anchor_ancestry, "a", index, node_name, node_parent
			)

			is_ancestor_of_button, button_id = add_to_hash_tree(
				button_ancestry, "button", index, node_name, node_parent
			)

			try:
				cursor = layout_node_index.index(
					index
				)  # todo replace this with proper cursoring, ignoring the fact this is O(n^2) for the moment
			except:
				continue

			if node_name in black_listed_elements:
				continue

			[x, y, width, height] = bounds[cursor]
			x /= device_pixel_ratio
			y /= device_pixel_ratio
			width /= device_pixel_ratio
			height /= device_pixel_ratio

			elem_left_bound = x
			elem_top_bound = y
			elem_right_bound = x + width
			elem_lower_bound = y + height

			partially_is_in_viewport = (
				elem_left_bound < win_right_bound
				and elem_right_bound >= win_left_bound
				and elem_top_bound < win_lower_bound
				and elem_lower_bound >= win_upper_bound
			)

			if not partially_is_in_viewport:
				continue

			meta_data = []

			# inefficient to grab the same set of keys for kinds of objects but its fine for now
			element_attributes = find_attributes(
				attributes[index], ["type", "placeholder", "aria-label", "title", "alt"]
			)

			ancestor_exception = is_ancestor_of_anchor or is_ancestor_of_button
			ancestor_node_key = (
				None
				if not ancestor_exception
				else str(anchor_id)
				if is_ancestor_of_anchor
				else str(button_id)
			)
			ancestor_node = (
				None
				if not ancestor_exception
				else child_nodes.setdefault(str(ancestor_node_key), [])
			)

			if node_name == "#text" and ancestor_exception:
				text = strings[node_value[index]]
				if text == "|" or text == "•":
					continue
				ancestor_node.append({
					"type": "type", "value": text
				})
			else:
				if (
					node_name == "input" and element_attributes.get("type") == "submit"
				) or node_name == "button":
					node_name = "button"
					element_attributes.pop(
						"type", None
					)  # prevent [button ... (button)..]
				
				for key in element_attributes:
					if ancestor_exception:
						ancestor_node.append({
							"type": "attribute",
							"key":  key,
							"value": element_attributes[key]
						})
					else:
						meta_data.append(element_attributes[key])

			element_node_value = None

			if node_value[index] >= 0:
				element_node_value = strings[node_value[index]]
				if element_node_value == "|": #commonly used as a seperator, does not add much context - lets save ourselves some token space
					continue
			elif (
				node_name == "input"
				and index in input_value_index
				and element_node_value is None
			):
				node_input_text_index = input_value_index.index(index)
				text_index = input_value_values[node_input_text_index]
				if node_input_text_index >= 0 and text_index >= 0:
					element_node_value = strings[text_index]

			# remove redudant elements
			if ancestor_exception and (node_name != "a" and node_name != "button"):
				continue

			row, p = None, index  #F:row
			while "row" in FIX and p >= 0 and row is None:  #F:row
				row = p if strings[node_names[p]].lower() == "tr" or find_attributes(attributes[p], ["role"]).get("role") == "row" else None  #F:row
				p = parent[p]  #F:row
			elements_in_view_port.append(
				{
					"row": row,  #F:row
					"node_index": str(index),
					"backend_node_id": backend_node_id[index],
					"node_name": node_name,
					"node_value": element_node_value,
					"node_meta": meta_data,
					"is_clickable": index in is_clickable,
					"origin_x": int(x),
					"origin_y": int(y),
					"center_x": int(x + (width / 2)),
					"center_y": int(y + (height / 2)),
				}
			)

		# lets filter further to remove anything that does not hold any text nor has click handlers + merge text from leaf#text nodes with the parent
		elements_of_interest= []
		id_counter 			= 0
		rows = {}  #F:row

		for element in elements_in_view_port:
			node_index = element.get("node_index")
			node_name = element.get("node_name")
			node_value = element.get("node_value")
			is_clickable = element.get("is_clickable")
			origin_x = element.get("origin_x")
			origin_y = element.get("origin_y")
			center_x = element.get("center_x")
			center_y = element.get("center_y")
			meta_data = element.get("node_meta")

			inner_text = f"{node_value} " if node_value else ""
			meta = ""
			
			if node_index in child_nodes:
				for child in child_nodes.get(node_index):
					entry_type = child.get('type')
					entry_value= child.get('value')

					if entry_type == "attribute":
						entry_key = child.get('key')
						meta_data.append(f'{entry_key}="{entry_value}"')
					else:
						inner_text += f"{entry_value} "

			if meta_data:
				meta_string = " ".join(meta_data)
				meta = f" {meta_string}"

			if element.get("row") is not None: meta += f" row={rows.setdefault(element['row'], len(rows) + 1)}"  #F:row
			if inner_text != "":
				inner_text = f"{inner_text.strip()}"

			converted_node_name = convert_name(node_name, is_clickable)

			# not very elegant, more like a placeholder
			if (
				(converted_node_name != "button" or meta == "")
				and converted_node_name != "link"
				and converted_node_name != "input"
				and converted_node_name != "img"
				and converted_node_name != "textarea"
			) and inner_text.strip() == "":
				continue

			page_element_buffer[id_counter] = element

			if inner_text != "": 
				elements_of_interest.append(
					f"""<{converted_node_name} id={id_counter}{meta}>{inner_text}</{converted_node_name}>"""
				)
			else:
				elements_of_interest.append(
					f"""<{converted_node_name} id={id_counter}{meta}/>"""
				)
			id_counter += 1

		print("Parsing time: {:0.2f} seconds".format(time.time() - start))
		return elements_of_interest

if (
	__name__ == "__main__"
):
	_crawler = Crawler()
	# EXTRA: Anthropic client; model + per-model request config from env
	MODEL = os.environ.get("NATBOT_MODEL", "claude-haiku-5-5")
	OAI = not MODEL.startswith("claude-")  # EXTRA: non-Claude models go through an OpenAI-compatible API (default OpenRouter)
	_client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"), max_retries=4) if not OAI else None
	_oai = __import__("openai").OpenAI(base_url=os.environ.get("NATBOT_OAI_BASE", "https://openrouter.ai/api/v1"), api_key=os.environ.get("OPENAI_API_KEY"), max_retries=4) if OAI else None
	VERBATIM = os.environ.get("NATBOT_VARIANT") == "verbatim"
	LOG = open(os.environ.get("NATBOT_LOG", "natbot-events.jsonl"), "a")
	def log(**kw):
		kw["t"] = int(time.time() * 1000); LOG.write(json.dumps(kw) + "\n"); LOG.flush()

	def print_help():
		print(
			"(g) to visit url\n(u) scroll up\n(d) scroll down\n(c) to click\n(t) to type\n" +
			"(h) to view commands again\n(r/enter) to run suggested command\n(o) change objective"
		)

	def get_gpt_command(objective, url, previous_command, browser_content):
		prompt = prompt_template
		prompt = prompt.replace("$objective", objective)
		prompt = prompt.replace("$url", url[:100])
		prompt = prompt.replace("$previous_command", previous_command)
		prompt = prompt.replace("$browser_content", browser_content[:(12000 if "page" in FIX else 4500)])  #F:page (upstream: [:4500])
		# EXTRA: was openai.Completion.create(model="text-davinci-002", prompt=prompt, temperature=0.5, best_of=10, n=3, max_tokens=50).
		# Same prompt, sent as one user message. temperature/best_of/n dropped (temperature 400s on current models; no best_of).
		# Haiku 5.5: thinking disabled (closest to a davinci completion). Opus 5.5 cannot disable thinking: effort "low".
		# max_tokens 50 -> 200 (Haiku) / 4000 (Opus, thinking included) so an ANSWER "..." line is not cut off.
		# One system line stands in for the completion format: a davinci completion of a prompt ending in "YOUR COMMAND:"
		# is a bare command; a chat model otherwise replies in prose (measured: plumbing run 1794324427, 19 of 22 replies were prose).
		kw = dict(system="Reply with exactly one command from the list above and nothing else.")
		if "stop" in FIX: kw["system"] += " If the objective is already achieved on the current page, reply with ANSWER."  #F:stop
		if VERBATIM:  # arm "verbatim": no system line, max_tokens 50 as upstream, upstream line-1 parser (below)
			kw = dict(max_tokens=50, thinking={"type": "disabled"})
		elif "opus" in MODEL:
			kw.update(max_tokens=4000, output_config={"effort": "low"})
		else:
			kw.update(max_tokens=200, thinking={"type": "disabled"})
		t0 = int(time.time() * 1000)
		content, i = prompt, prompt.index("The current browser content, objective")  #F:cache
		if "cache" in FIX: content = [{"type": "text", "text": prompt[:i], "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": prompt[i:]}]  #F:cache
		cost = None
		if OAI:  # EXTRA: OpenAI-compatible arm (OpenRouter by default), minimal reasoning, provider-reported cost
			r = _oai.chat.completions.create(model=MODEL, max_tokens=200, extra_body={"reasoning": {"effort": os.environ.get("NATBOT_OAI_EFFORT", "minimal")}, "usage": {"include": True}},
				messages=[{"role": "system", "content": kw["system"]}, {"role": "user", "content": prompt}] if "system" in kw else [{"role": "user", "content": prompt}])
			text, u, stop = r.choices[0].message.content or "", r.usage, r.choices[0].finish_reason
			cr = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
			usage = {"input": u.prompt_tokens - cr, "cache_read": cr, "cache_write": 0, "output": u.completion_tokens}
			cost = getattr(u, "cost", None) if getattr(u, "cost", None) is not None else (u.model_extra or {}).get("cost")
		else:
			response = _client.messages.create(model=MODEL, messages=[{"role": "user", "content": content}], **kw)
			text, u, stop = "".join(b.text for b in response.content if b.type == "text"), response.usage, response.stop_reason
			usage = {"input": u.input_tokens, "cache_read": u.cache_read_input_tokens or 0, "cache_write": u.cache_creation_input_tokens or 0, "output": u.output_tokens}
		log(ev="llm", t0=t0, text=text, stop=stop, usage=usage, cost_usd=cost, url=url, content_chars=len(browser_content), content=browser_content[:4500], fixes=sorted(FIX - {""}))
		if VERBATIM:
			return text
		# EXTRA: chat models may add a preamble; pick the first line that is a command (upstream takes line 1)
		for line in text.strip().split("\n"):
			if line.strip().strip("`").startswith(("SCROLL", "CLICK", "TYPE", "ANSWER")):
				return line.strip().strip("`")
		return text

	def run_cmd(cmd):
		cmd = cmd.split("\n")[0]

		if cmd.startswith("ANSWER"):  # EXTRA: stop command (upstream loops until a human stops it)
			text = cmd[len("ANSWER"):].strip()
			text = text[1:-1] if len(text) >= 2 and text[0] == '"' and text[-1] == '"' else text.lstrip('"')
			open(os.environ.get("NATBOT_ANSWER", "answer.txt"), "w").write(text)
			log(ev="answer", text=text)
			exit(0)
		elif cmd.startswith("SCROLL UP"):
			_crawler.scroll("up")
		elif cmd.startswith("SCROLL DOWN"):
			_crawler.scroll("down")
		elif cmd.startswith("CLICK"):
			commasplit = cmd.split(",")
			id = commasplit[0].split(" ")[1]
			_crawler.click(id)
		elif cmd.startswith("TYPE"):
			spacesplit = cmd.split(" ")
			id = spacesplit[1]
			text = spacesplit[2:]
			text = " ".join(text)
			# Strip leading and trailing double quotes
			text = text[1:-1]

			if cmd.startswith("TYPESUBMIT"):
				text += '\n'
			_crawler.type(id, text)

		time.sleep(2)

	objective = "Make a reservation for 2 at 7pm at bistro vida in menlo park"
	print("\nWelcome to natbot! What is your objective?")
	i = input()
	if len(i) > 0:
		objective = i

	gpt_cmd = ""
	prev_cmd = ""
	_crawler.go_to_page(os.environ.get("NATBOT_START_URL", "google.com"))  # EXTRA: task start_url (upstream: google.com)
	max_steps = int(os.environ.get("NATBOT_MAX_STEPS", "40"))  # EXTRA: step cap (upstream: unbounded)
	n_steps = 0
	history = []  #F:mem
	try:
		while True:
			n_steps += 1
			if n_steps > max_steps:
				log(ev="step_cap", n=max_steps); exit(3)
			log(ev="turn_start", n=n_steps)
			try:  # EXTRA: a crawl can race a navigation; upstream would crash, a human would just retry
				browser_content = "\n".join(_crawler.crawl())
			except Exception as e:
				log(ev="crawl_error", err=str(e)[:300]); time.sleep(1)
				browser_content = "\n".join(_crawler.crawl())
			prev_cmd = gpt_cmd
			if "mem" in FIX: prev_cmd = "\n".join(history[-10:]) or "(none)"  #F:mem
			gpt_cmd = get_gpt_command(objective, _crawler.page.url, prev_cmd, browser_content)
			gpt_cmd = gpt_cmd.strip()

			if not quiet:
				print("URL: " + _crawler.page.url)
				print("Objective: " + objective)
				print("----------------\n" + browser_content + "\n----------------\n")
			if len(gpt_cmd) > 0:
				print("Suggested command: " + gpt_cmd)


			command = input()
			if command == "r" or command == "":  # EXTRA: stdin is a scripted "yes" (empty lines) = run every suggestion
				t_cmd = int(time.time() * 1000)
				try:
					run_cmd(gpt_cmd)
					tgt = next((l for l in browser_content.split("\n") if gpt_cmd.split(" ")[0] in ("CLICK", "TYPE", "TYPESUBMIT") and l.startswith("<") and f" id={gpt_cmd.split(' ')[1]} " in l.split(">")[0].replace("/", " ") + " "), "") if "mem" in FIX else ""  #F:mem
					if "mem" in FIX: history.append(f"{gpt_cmd}   [on: {tgt[:120]}]" if tgt else gpt_cmd)  #F:mem
					# EXTRA: ok = natbot recognised a command (upstream silently ignores anything else)
					log(ev="cmd", t0=t_cmd, cmd=gpt_cmd, ok=gpt_cmd.startswith(("SCROLL UP", "SCROLL DOWN", "CLICK", "TYPE")))
				except SystemExit:
					raise
				except Exception as e:  # EXTRA: upstream would crash on a malformed command; log it and go on
					log(ev="cmd", t0=t_cmd, cmd=gpt_cmd, ok=False, err=str(e)[:300])
			elif command == "g":
				url = input("URL:")
				_crawler.go_to_page(url)
			elif command == "u":
				_crawler.scroll("up")
				time.sleep(1)
			elif command == "d":
				_crawler.scroll("down")
				time.sleep(1)
			elif command == "c":
				id = input("id:")
				_crawler.click(id)
				time.sleep(1)
			elif command == "t":
				id = input("id:")
				text = input("text:")
				_crawler.type(id, text)
				time.sleep(1)
			elif command == "o":
				objective = input("Objective:")
			else:
				print_help()
	except KeyboardInterrupt:
		print("\n[!] Ctrl+C detected, exiting gracefully.")
		exit(0)
