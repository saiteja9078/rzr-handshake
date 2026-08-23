The track im picking is:

AI Growth & Agentic Commerce
Grow the merchant’s revenue, and make them sellable to AI buyers


Okay first thing before creating the repository is to find a name for that, the name came from that buildathon problem statement naming itself.
It is like a handshake between buyer and seller.

Build an agent that grows revenue for a merchant on Razorpay test-mode APIs, or that makes a merchant transactable by an AI buyer end to end.
Im picking the second one: makes a merchant transactable by an AI buyer end to end.
example directions:
  Conversational in-app checkout
  Agent-readable catalog
  Upsell & cross-sell agent
  Campaign orchestrator

Based on the branch i picked the directions i can go is Conversational in app checkout, which lets user order anything in chat mode in order that to be possible i also should include the second one: agent readable catalog that bridges the gap between agent and products in e commerce page.
Because an agent reading data from a structured catalogue can understand bettter than an agent reading a raw dom.
and again we will have tradeoffs here in dom the agent can see everything, where as in a structured api or a catalogue the agent has to query for anything. Its a tradeoff between visibility and precise detailing.
This whole thing is one component.

lets once go thru the request lifecycle of a customer so that we will encounter all the things to do.

first phase is getting the intent of the customer
users asks a query can be of any type from the following

can ask show me n shoes within this prices range. obviously agent should go thru the ratings and resolve them right.
can ask to buy a product directly, human is asked for verfication
or any random review queries asking how is this product, which colour looks amazing.

with all of these agent should go thru reviews and while asking for verfication it should show the reviews summary or ratings to the user. If we only have to make profit for the merchant we have to think again about this thing. Beacuse this statement also goes in customers favor cannot blindly mislead customer saying its a good product for a bad one.

the next phase would be
findingn the product/s that customer needs
let customer seelct and ask the agent select the beset one if multiple products are shown., if only one is shown ask for confirmation.

the next phase is payement confirmation
ask for confirmation of the payment and done, record the data in the database that he bought this product.


think about stock updates in between, the stock updates should be pushed to the user while buying only it shouldnt be a static product card.
Sock can be completed while the agent is reasoning about makeing transaciotn and all think about this.

every decision made by the agent should explainable.
handle failures, retries and all
and persist whole conversation in the chat history, the user can anytime come and complete the transaction, if the transaction isnt completed.

First thing to think about is:
Designing an api that agent can browse the products with a broader view as well as better detailing rather than dom views.

How:
Take the query from the user either its a specific with all the requirements or vague
specific mean: red coloured table, under 5k with n star rating
vague query: a table -> how do ypu handle this qwuery?

first apply and search for all the products that user needs
api returns a page of products with the requirements order by rating in descending order
and each product will also have a page of reviews to inspect about the product should contain n good reviews and n bad reviews if agent wants to inspect on that particular product it queries untill that rest of the data is cached on frontend.
on what basis agent should fetch more reviews or more products
it should trust the good reviews or bad reviews, maybe depends on rating a good avg rating with reasonable amount of ratings can make the decision here but how?
lets say a prodcut had 3 star avg rating with 58954 ratings it is a reasonable choice, if the issue is related to packaing or something that will not happen very likely agent can reason on the reviews given it can select this product.

We are limiting the reviews because agent can digest all the products info and reason to select the right one.

question: am i going too deep towards customers favor but the problem statement is to make revenue for merchants. If i depend too much on reviews and ratings to select the products how does this make revenue for merchants with less ratinsg and reviews? But still a customer while buying the prodcut sitll sess the rating and reviews right? think about this

Make a merchant transactable by an AI buyer end to end. this is what we have picked that means ai has to make a reliable transaction with the merchant thats it nothing much to worry about. :)
Unlike ads driven discovery, a merchant becomes 'sellable to AI buyers' by having good products and honest data, not ad spend. This is a structural shift.

the chain we got at last: take user query -> fetch a page of prodcuts nested with a page of reviewws for each product -> if you want more prodcuts can fetch -> if you want more reviews can fetch -> selected n prodcuts -> show them to user, here user can increase quantity select the prodcut, change the colour, show him with the reivews summary you had.
The time in which the user is selecting the product and or making colour changes what ever, the stock chanages should be streaed to the user making sure he was aware so that can take decisions faster if the stock is lesser.
So user had selected the product now the patement phase, i dont know that much about payements so we have to look inot it.


Theres something i need to confirm first, 

Build an agent that grows revenue for a merchant on Razorpay test-mode APIs, or that makes a merchant transactable by an AI buyer end to end.

It is mentioned that to make merchant transactable for an ai buyer. Im not getting if we have just build the infra for the llm to access the prodcuts.
or we also have create that agent ourselves.
The first sounds similar,but in example directions it is also listed this: Conversational in-app checkout
That means we can also develop the agent ourselves? i think so...

we will do both of them but we will focus mainly on infra that agent interacts.

Lets deeply discuss about the infra first.

Lets think about what does an agent requrired to pick up products it wants.
Maybe an api that serves products it wants by applying all the filters.

Another doubt again, are we really allowed to create our own schema and apply filters as our wish like it should also work with the real world or not?
maybe i can because i need something to test on, so i can create my schema.

First we should think of how do we store products we should store the products matching real world ecommerce platforms.

The first thing that comes into my mind is to use sql for merchant data and customer data
and no sql for product listing.

but it might create a oroblem transactions should be atomic right we have things scattered inventory is in no sql and payment informations are in sql. This creates more complexity.
So lets fall back to plain sql database only.
In plain sql database only we can store the product card information but this creates problems right, if sotre the product information as jsob, how cna you track the category specific stocks

Okay now lets research about this things are implemented or not, if implemented what are the gaps that we can fill.

https://stripe.com/in/guides/agentic-commerce

While researching i found that open ai and stripe has partnered for this, but why did they backed out
also amazon has blocked chat gpt or any other models from browsing the products so that users go directly into amazong and amazon can show them ads.

we can do this, build an mcp server and expose it to claude or chat gpt.
but it becomes complex exposing payement apis to a third party llm provider.
we should secure it lets see...

This dependency on a third party LLM provider for both conversation and payment auth is a real risk we can't fully control Claude Desktop or ChatGPT Desktop's UI, approval flow, or availability during judging. So we're keeping the MCP server as our open, interface (any agent can browse and query it), but the actual state machine pending orders, spend bounds, stock checks, signature verification, and the final payment gate lives entirely in our own server code, never trusted to the LLM's word alone. We'll build a minimal client of our own as the primary demo surface, so the gating and audit trail are things we visibly own and can defend, not something we ask the panel to trust because a third party client asked for permission. Claude/GPT Desktop can still connect to the same server as a secondary demo, proving the protocol is genuinely open just not our load-bearing safety mechanism.

