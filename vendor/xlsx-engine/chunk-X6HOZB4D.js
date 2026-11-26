// src/workbook-xml.ts
var decodeArchive;
function configureWorkbookArchiveDecoder(decode) {
  decodeArchive = decode;
}
function decodeWorkbookArchive(bytes) {
  if (!decodeArchive) throw new Error("The workbook archive decoder is not initialized.");
  return decodeArchive(bytes);
}
var decodeXml;
var trees = /* @__PURE__ */ new Map();
var owners = /* @__PURE__ */ new Map();
var ownedKeys = /* @__PURE__ */ new Map();
var XMLNS = "http://www.w3.org/2000/xmlns/";
var XML = "http://www.w3.org/XML/1998/namespace";
function configureWorkbookXmlDecoder(decode) {
  decodeXml = decode;
}
function takeWorkbookXmlRecords(keep) {
  const records = Array.from(trees).filter(([xml]) => !keep || keep.has(xml));
  trees.clear();
  return records;
}
function retainTree(xml, tree, cacheOwners) {
  trees.set(xml, tree);
  for (const owner of cacheOwners) {
    const keys = ownedKeys.get(owner);
    if (!keys) continue;
    keys.add(xml);
    let set = owners.get(xml);
    if (!set) owners.set(xml, set = /* @__PURE__ */ new Set());
    set.add(owner);
  }
}
var ParsedNode = class _ParsedNode {
  nodeType;
  descendants;
  parentNode = null;
  ownerDocument;
  childNodes = [];
  name;
  localName;
  prefix;
  data;
  attributeValues = /* @__PURE__ */ new Map();
  explicitNamespace;
  constructor(document, type, name = "", data = "") {
    this.ownerDocument = document;
    this.nodeType = type;
    this.name = name;
    const colon = name.indexOf(":");
    this.localName = colon < 0 ? name : name.slice(colon + 1);
    this.prefix = colon < 0 ? null : name.slice(0, colon);
    this.data = data;
  }
  get tagName() {
    return this.name;
  }
  get nodeName() {
    return this.name || (this.nodeType === 3 ? "#text" : "#document");
  }
  get nodeValue() {
    return this.nodeType === 3 ? this.data : null;
  }
  get namespaceURI() {
    return this.explicitNamespace !== void 0 ? this.explicitNamespace : this.lookupNamespaceURI(this.prefix);
  }
  get children() {
    return this.childNodes.filter((node) => node.nodeType === 1);
  }
  get firstChild() {
    return this.childNodes[0] ?? null;
  }
  get firstElementChild() {
    return this.children[0] ?? null;
  }
  get parentElement() {
    return this.parentNode?.nodeType === 1 ? this.parentNode : null;
  }
  get nextSibling() {
    return this.parentNode?.childNodes[this.parentNode.childNodes.indexOf(this) + 1] ?? null;
  }
  get textContent() {
    return this.nodeType === 3 ? this.data : this.childNodes.map((node) => node.textContent).join("");
  }
  set textContent(text) {
    if (this.nodeType === 3) {
      this.data = text;
      return;
    }
    this.childNodes.forEach((node) => {
      node.parentNode = null;
    });
    this.childNodes = [];
    this.ownerDocument.version++;
    if (text) this.appendChild(this.ownerDocument.createTextNode(text));
  }
  get attributes() {
    return Array.from(this.attributeValues, ([name, value]) => ({
      name,
      value,
      localName: name.split(":").at(-1),
      namespaceURI: name === "xmlns" || name.startsWith("xmlns:") ? XMLNS : name.includes(":") ? this.lookupNamespaceURI(name.split(":")[0]) : null
    }));
  }
  lookupNamespaceURI(prefix) {
    if (prefix === "xml") return XML;
    if (prefix === "xmlns") return XMLNS;
    const key = prefix ? `xmlns:${prefix}` : "xmlns";
    return this.attributeValues.get(key) ?? this.parentNode?.lookupNamespaceURI(prefix) ?? null;
  }
  getAttribute(name) {
    return this.attributeValues.get(name) ?? null;
  }
  hasAttribute(name) {
    return this.attributeValues.has(name);
  }
  getAttributeNS(namespace, localName) {
    return this.attributes.find((attribute) => attribute.namespaceURI === namespace && attribute.localName === localName)?.value ?? null;
  }
  setAttribute(name, value) {
    this.attributeValues.set(name, String(value));
  }
  setAttributeNS(namespace, name, value) {
    this.setAttribute(name, value);
    const prefix = name.includes(":") ? name.split(":")[0] : null;
    if (namespace && namespace !== XMLNS && prefix && this.lookupNamespaceURI(prefix) !== namespace) {
      this.setAttribute(`xmlns:${prefix}`, namespace);
    }
  }
  removeAttribute(name) {
    this.attributeValues.delete(name);
  }
  appendChild(node) {
    node.remove();
    node.parentNode = this;
    this.childNodes.push(node);
    this.ownerDocument.version++;
    return node;
  }
  insertBefore(node, successor) {
    if (!successor) return this.appendChild(node);
    if (node === successor) return node;
    node.remove();
    const index = this.childNodes.indexOf(successor);
    if (index < 0) throw new Error("XML insertion target is not a child.");
    node.parentNode = this;
    this.childNodes.splice(index, 0, node);
    this.ownerDocument.version++;
    return node;
  }
  removeChild(node) {
    const index = this.childNodes.indexOf(node);
    if (index >= 0) {
      this.childNodes.splice(index, 1);
      node.parentNode = null;
      this.ownerDocument.version++;
    }
    return node;
  }
  remove() {
    this.parentNode?.removeChild(this);
  }
  cloneNode(deep = false) {
    const node = new _ParsedNode(this.ownerDocument, this.nodeType, this.name, this.data);
    node.attributeValues = new Map(this.attributeValues);
    node.explicitNamespace = this.namespaceURI;
    for (const attribute of this.attributes) {
      if (attribute.namespaceURI && attribute.namespaceURI !== XMLNS && attribute.name.includes(":")) {
        node.attributeValues.set(`xmlns:${attribute.name.split(":")[0]}`, attribute.namespaceURI);
      }
    }
    if (deep) this.childNodes.forEach((child) => node.appendChild(child.cloneNode(true)));
    return node;
  }
  getElementsByTagName(name) {
    if (this.descendants?.version === this.ownerDocument.version) return name === "*" ? this.descendants.nodes : this.descendants.nodes.filter((node) => node.name === name);
    const nodes = [];
    const visit = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType !== 1) continue;
        nodes.push(child);
        visit(child);
      }
    };
    visit(this);
    this.descendants = { version: this.ownerDocument.version, nodes };
    return name === "*" ? nodes : nodes.filter((node) => node.name === name);
  }
  getElementsByTagNameNS(namespace, localName) {
    return this.getElementsByTagName("*").filter((node) => (namespace === "*" || node.namespaceURI === namespace) && (localName === "*" || node.localName === localName));
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] ?? null;
  }
  querySelectorAll(selector) {
    const names = selector.split(",").map((name) => name.trim());
    if (names.some((name) => !/^[\w:-]+$/.test(name))) throw new Error("Unsupported XML selector.");
    return this.getElementsByTagName("*").filter((node) => names.includes(node.localName) || names.includes(node.name));
  }
};
var ParsedDocument = class _ParsedDocument extends ParsedNode {
  version = 0;
  cacheOwners = /* @__PURE__ */ new Set();
  constructor() {
    super(null, 9);
    this.ownerDocument = this;
  }
  get documentElement() {
    return this.firstElementChild;
  }
  implementation = {
    createDocument: (namespace, name) => {
      const document = new _ParsedDocument();
      document.cacheOwners = new Set(this.cacheOwners);
      if (name) document.appendChild(document.createElementNS(namespace, name));
      return document;
    }
  };
  createElementNS(namespace, name) {
    const node = new ParsedNode(this, 1, name);
    node.explicitNamespace = namespace;
    return node;
  }
  createTextNode(text) {
    return new ParsedNode(this, 3, "", text);
  }
  importNode(node, deep) {
    const copy = node.cloneNode(deep);
    const attach = (child) => {
      child.ownerDocument = this;
      child.childNodes.forEach(attach);
    };
    attach(copy);
    return copy;
  }
};
function hydrate(tree, document, parent) {
  for (const child of tree[2]) {
    if (typeof child === "string") {
      parent.appendChild(document.createTextNode(child));
      continue;
    }
    const node = new ParsedNode(document, 1, child[0]);
    node.attributeValues = new Map(child[1]);
    parent.appendChild(node);
    hydrate(child, document, node);
  }
}
function parseWorkbookXml(xml) {
  let tree = trees.get(xml);
  if (!tree) {
    if (!decodeXml) throw new Error("The workbook XML decoder is not initialized.");
    tree = JSON.parse(decodeXml(xml));
    trees.set(xml, tree);
  }
  const document = new ParsedDocument();
  document.cacheOwners = new Set(owners.get(xml));
  hydrate(tree, document, document);
  return document;
}
function serializeWorkbookXml(source) {
  const root = source;
  const escape = (text) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const attribute = (text) => escape(text).replace(/"/g, "&quot;").replace(/\r/g, "&#13;").replace(/\n/g, "&#10;").replace(/\t/g, "&#9;");
  const serialize = (node, inherited) => {
    if (node.nodeType === 3) return escape(node.data);
    if (node.nodeType === 9) return node.childNodes.map((child) => serialize(child, inherited)).join("");
    const attrs = new Map(node.attributeValues);
    const namespaces = new Map(inherited);
    for (const [key, value] of attrs) if (key === "xmlns" || key.startsWith("xmlns:")) namespaces.set(key, value);
    const namespace = node.namespaceURI;
    const declaration = node.prefix ? `xmlns:${node.prefix}` : "xmlns";
    if (namespace && namespaces.get(declaration) !== namespace) {
      attrs.set(declaration, namespace);
      namespaces.set(declaration, namespace);
    }
    if (!namespace && !node.prefix && namespaces.get("xmlns")) {
      attrs.set("xmlns", "");
      namespaces.set("xmlns", "");
    }
    for (const attr of node.attributes) {
      if (!attr.namespaceURI || attr.namespaceURI === XMLNS || attr.namespaceURI === XML || !attr.name.includes(":")) continue;
      const key = `xmlns:${attr.name.split(":")[0]}`;
      if (namespaces.get(key) !== attr.namespaceURI) {
        attrs.set(key, attr.namespaceURI);
        namespaces.set(key, attr.namespaceURI);
      }
    }
    const start = `<${node.name}${Array.from(attrs, ([key, value]) => ` ${key}="${attribute(value)}"`).join("")}`;
    node.attributeValues = attrs;
    return node.childNodes.length ? `${start}>${node.childNodes.map((child) => serialize(child, namespaces)).join("")}</${node.name}>` : `${start}/>`;
  };
  const xml = serialize(root, /* @__PURE__ */ new Map());
  const flatten = (node) => node.nodeType === 3 ? node.data : [node.name, Array.from(node.attributeValues), node.childNodes.map(flatten)];
  retainTree(xml, root.nodeType === 9 ? flatten(root) : ["", [], [flatten(root)]], root.ownerDocument.cacheOwners);
  return xml;
}
function installWorkerXmlAdapters() {
  Object.assign(globalThis, {
    DOMParser: class {
      parseFromString(xml) {
        return parseWorkbookXml(xml);
      }
    },
    XMLSerializer: class {
      serializeToString(node) {
        return serializeWorkbookXml(node);
      }
    },
    Node: { ELEMENT_NODE: 1, TEXT_NODE: 3, DOCUMENT_NODE: 9 }
  });
}

export {
  configureWorkbookArchiveDecoder,
  decodeWorkbookArchive,
  configureWorkbookXmlDecoder,
  takeWorkbookXmlRecords,
  parseWorkbookXml,
  serializeWorkbookXml,
  installWorkerXmlAdapters
};
//# sourceMappingURL=chunk-X6HOZB4D.js.map