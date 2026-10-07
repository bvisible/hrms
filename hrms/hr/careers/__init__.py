# //// Neoffice — added file (no upstream equivalent): the careers page of a Neoffice website
# //// (neoffice-maintenance#1294).
"""The careers page: job openings published from HR, applications, and Nora's reading of them.

Everything lives in hrms, the app that holds the data (Jérémy, 2026-10-07: a plugin is whole in
one app). hrms declares a website plugin, `jobs`, to Builder's registry; the site switches it on or
off, and HR publishes or withdraws each opening. The page exists only when the plugin is on AND
something is open (a published opening, or unsolicited applications), as /reserver does.

- `plugin`: the switch, whether the page is open, the menu entry;
- `openings`: the openings a visitor may see, their route and their facts;
- `pages`: the context of /jobs and /jobs/<opening>;
- `apply`: the application endpoint (guest), with one typed upload per requested document;
- `notify`: the recruiter's e-mail and the applicant's acknowledgement;
- `share`, `seo`, `share_image`: sharing links, metadata, JSON-LD, the share picture, the sitemap;
- `extract`, `scoring`, `review`: Nora's reading — text of the documents, scores computed here
  from the opening's criteria, never read from the model, and never a decision;
- `retention`: applications deleted after the decision, unless the applicant agreed to be kept;
- `api`: what NORA's HR pole asks (read, and re-read on request).
"""

PLUGIN_NAME = "jobs"
ROUTE_PREFIX = "jobs"

DOCUMENT_TYPES = (
	"CV",
	"Cover Letter",
	"Work Certificates",
	"Diplomas",
	"Work Permit",
	"References",
	"Portfolio",
	"Other",
)
