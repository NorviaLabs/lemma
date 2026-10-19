// A link to one question (faq#key-safe) opens it: browsers scroll to a closed <details> but leave it shut.
function openLinkedQuestion() {
  const q = location.hash.length > 1 && document.getElementById(decodeURIComponent(location.hash.slice(1)));
  if (q && q.tagName === "DETAILS") { q.open = true; q.scrollIntoView(); }
}
addEventListener("hashchange", openLinkedQuestion);
openLinkedQuestion();
