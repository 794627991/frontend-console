// Understand-Anything architecture structural analysis script
const fs = require('fs');

const [inPath, outPath] = process.argv.slice(2);
if (!inPath || !outPath) { console.error('usage: node ua-arch-analyze.js <input.json> <output.json>'); process.exit(1); }

const input = JSON.parse(fs.readFileSync(inPath, 'utf8'));
const { fileNodes, importEdges, allEdges } = input;

// ---- A. Directory grouping ----
const paths = fileNodes.map(n => n.filePath);
// compute common path prefix (directory-wise)
function segs(p) { return p.split('/').filter(Boolean); }
let commonSegs = null;
for (const p of paths) {
  const s = segs(p);
  if (commonSegs === null) commonSegs = s.slice(0, -1);
  else {
    let i = 0;
    while (i < commonSegs.length && i < s.length - 1 && commonSegs[i] === s[i]) i++;
    commonSegs = commonSegs.slice(0, i);
  }
}
const prefixLen = commonSegs ? commonSegs.length : 0;

const dirGroups = {};
const groupOf = {};
for (const n of fileNodes) {
  const s = segs(n.filePath);
  const rest = s.slice(prefixLen);
  let group = rest.length > 1 ? rest.slice(0, rest.length - 1).join('/') : (rest.length === 1 ? '(root)' : '(root)');
  if (rest.length > 1) group = rest[0]; // group by first dir segment after prefix (or first segment if no common prefix)
  else group = '(root)';
  (dirGroups[group] = dirGroups[group] || []).push(n.id);
  groupOf[n.id] = group;
}

// ---- B. Node type grouping ----
const nodeTypeGroups = {};
for (const n of fileNodes) (nodeTypeGroups[n.type] = nodeTypeGroups[n.type] || []).push(n.id);

// ---- C. Import adjacency: fan-in / fan-out ----
const fanOut = {}, fanIn = {};
for (const e of importEdges) {
  fanOut[e.source] = (fanOut[e.source] || 0) + 1;
  fanIn[e.target] = (fanIn[e.target] || 0) + 1;
}

// ---- D. Cross-category dependency analysis ----
const typeOf = {};
for (const n of fileNodes) typeOf[n.id] = n.type;
const crossCat = {};
for (const e of allEdges) {
  const a = typeOf[e.source], b = typeOf[e.target];
  if (a === b) continue;
  const key = `${a}->${b}|${e.type}`;
  crossCat[key] = (crossCat[key] || 0) + 1;
}
const crossCategoryEdges = Object.entries(crossCat).map(([k, count]) => {
  const [pair, edgeType] = k.split('|');
  const [fromType, toType] = pair.split('->');
  return { fromType, toType, edgeType, count };
});

// ---- E. Inter-group import frequency ----
const interMap = {};
for (const e of importEdges) {
  const g1 = groupOf[e.source], g2 = groupOf[e.target];
  if (g1 === undefined || g2 === undefined) continue;
  const key = `${g1}->${g2}`;
  interMap[key] = (interMap[key] || 0) + 1;
}
const interGroupImports = Object.entries(interMap).map(([k, count]) => {
  const [from, to] = k.split('->');
  return { from, to, count };
});

// ---- F. Intra-group import density ----
const intraGroupDensity = {};
for (const g of Object.keys(dirGroups)) intraGroupDensity[g] = { internalEdges: 0, totalEdges: 0, density: 0 };
for (const e of importEdges) {
  const g1 = groupOf[e.source], g2 = groupOf[e.target];
  if (g1 !== undefined) { intraGroupDensity[g1].totalEdges++; if (g1 === g2) intraGroupDensity[g1].internalEdges++; }
  if (g2 !== undefined && g1 !== g2) intraGroupDensity[g2].totalEdges++;
}
for (const g of Object.keys(intraGroupDensity)) {
  const d = intraGroupDensity[g];
  d.density = d.totalEdges ? +(d.internalEdges / d.totalEdges).toFixed(3) : 0;
}

// ---- G. Directory pattern matching ----
const patternTable = {
  routes: 'api', api: 'api', controllers: 'api', endpoints: 'api', handlers: 'api',
  services: 'service', core: 'service', lib: 'service', domain: 'service', logic: 'service',
  models: 'data', db: 'data', data: 'data', persistence: 'data', repository: 'data', entities: 'data',
  components: 'ui', views: 'ui', pages: 'ui', ui: 'ui', layouts: 'ui', screens: 'ui',
  middleware: 'middleware', plugins: 'middleware', interceptors: 'middleware', guards: 'middleware',
  utils: 'utility', helpers: 'utility', common: 'utility', shared: 'utility', tools: 'utility',
  config: 'config', constants: 'config', env: 'config', settings: 'config',
  __tests__: 'test', test: 'test', tests: 'test', spec: 'test', specs: 'test',
  types: 'types', interfaces: 'types', schemas: 'types', contracts: 'types', dtos: 'types',
  hooks: 'hooks',
  store: 'state', state: 'state', reducers: 'state', actions: 'state', slices: 'state',
  assets: 'assets', static: 'assets', public: 'assets',
  migrations: 'data', management: 'config', commands: 'config', templatetags: 'utility',
  signals: 'service', serializers: 'api', cmd: 'entry', internal: 'service', pkg: 'utility',
  bin: 'entry', docs: 'documentation', documentation: 'documentation', wiki: 'documentation',
  deploy: 'infrastructure', deployment: 'infrastructure', infra: 'infrastructure', infrastructure: 'infrastructure',
  '.github': 'ci-cd', '.gitlab': 'ci-cd', '.circleci': 'ci-cd',
  k8s: 'infrastructure', kubernetes: 'infrastructure', helm: 'infrastructure', charts: 'infrastructure',
  terraform: 'infrastructure', tf: 'infrastructure', docker: 'infrastructure',
  sql: 'data', database: 'data', schema: 'data',
};
function filePattern(n) {
  const p = n.filePath, base = n.name;
  if (/(\.test\.|\.spec\.|^test_.*\.py$|_test\.go$|Test\.java$|_spec\.rb$|Tests\.cs$)/.test(base)) return 'test';
  if (/\.d\.ts$/.test(base)) return 'types';
  if (base === '__init__.py' || base === 'index.js' || base === 'index.ts') return 'entry';
  if (base === 'manage.py') return 'entry';
  if (base === 'wsgi.py' || base === 'asgi.py') return 'config';
  if (base === 'config.ru') return 'entry';
  if (['Cargo.toml','go.mod','Gemfile','pom.xml','build.gradle','composer.json','package.json'].includes(base)) return 'config';
  if (/^Dockerfile/.test(base) || /^docker-compose\./.test(base)) return 'infrastructure';
  if (/\.tf$|\.tfvars$/.test(base)) return 'infrastructure';
  if (/workflows\/|\.gitlab-ci\.yml$|Jenkinsfile/.test(p)) return 'ci-cd';
  if (/\.sql$/.test(base)) return 'data';
  if (/\.(graphql|gql|proto)$/.test(base)) return 'types';
  if (/\.(md|rst)$/.test(base)) return 'documentation';
  if (base === 'Makefile') return 'infrastructure';
  return null;
}
const patternMatches = {};
for (const [g, idsArr] of Object.entries(dirGroups)) {
  const seg = segs(g.includes('/') ? g : (g === '(root)' ? '' : g));
  let label = null;
  for (const s of seg) { if (patternTable[s.toLowerCase()]) { label = patternTable[s.toLowerCase()]; break; } }
  patternMatches[g] = label;
}
const fileLevelPatterns = {};
for (const n of fileNodes) { const p = filePattern(n); if (p) fileLevelPatterns[n.id] = p; }

// ---- H. Deployment topology ----
const infraFiles = fileNodes.filter(n =>
  /Dockerfile|docker-compose|\.tf$|k8s|helm|Jenkinsfile|gitlab-ci|workflows|Makefile/i.test(n.filePath)
).map(n => n.id);
const deploymentTopology = {
  hasDockerfile: fileNodes.some(n => /^Dockerfile/.test(n.name)),
  hasCompose: fileNodes.some(n => /^docker-compose\./.test(n.name)),
  hasK8s: false, hasTerraform: false,
  hasCI: fileNodes.some(n => /workflows|Jenkinsfile|gitlab-ci/i.test(n.filePath)),
  infraFiles,
};

// ---- I. Data pipeline detection ----
const dataPipeline = {
  schemaFiles: fileNodes.filter(n => /\.(sql|graphql|gql|proto|prisma)$/.test(n.name)).map(n => n.id),
  migrationFiles: fileNodes.filter(n => /migration/i.test(n.filePath)).map(n => n.id),
  dataModelFiles: fileNodes.filter(n => n.tags && n.tags.some(t => /data-model|entity|schema/i.test(t))).map(n => n.id),
  apiHandlerFiles: fileNodes.filter(n => n.tags && n.tags.some(t => /api-handler|flask|endpoint/i.test(t))).map(n => n.id),
};

// ---- J. Documentation coverage ----
const docFiles = fileNodes.filter(n => n.type === 'document').map(n => n.id);
const groupsWithDocs = new Set();
for (const d of docFiles) { const g = groupOf[d]; if (g) groupsWithDocs.add(g); }
const totalGroups = Object.keys(dirGroups).length;
const docCoverage = {
  groupsWithDocs: groupsWithDocs.size,
  totalGroups,
  coverageRatio: totalGroups ? +(groupsWithDocs.size / totalGroups).toFixed(2) : 0,
  undocumentedGroups: Object.keys(dirGroups).filter(g => !groupsWithDocs.has(g)),
};

// ---- K. Dependency direction ----
const dirPair = {};
for (const { from, to, count } of interGroupImports) {
  if (from === to) continue;
  const key = [from, to].sort().join('|');
  dirPair[key] = dirPair[key] || {};
  dirPair[key][`${from}->${to}`] = count;
}
const dependencyDirection = [];
for (const [key, m] of Object.entries(dirPair)) {
  const [a, b] = key.split('|');
  const ab = m[`${a}->${b}`] || 0, ba = m[`${b}->${a}`] || 0;
  if (ab > ba) dependencyDirection.push({ dependent: a, dependsOn: b, weight: ab - ba });
  else if (ba > ab) dependencyDirection.push({ dependent: b, dependsOn: a, weight: ba - ab });
}

// ---- stats ----
const filesPerGroup = {};
for (const [g, idsArr] of Object.entries(dirGroups)) filesPerGroup[g] = idsArr.length;
const nodeTypeCounts = {};
for (const [t, idsArr] of Object.entries(nodeTypeGroups)) nodeTypeCounts[t] = idsArr.length;

const output = {
  scriptCompleted: true,
  commonPrefix: commonSegs ? commonSegs.join('/') : '',
  directoryGroups: dirGroups,
  nodeTypeGroups,
  crossCategoryEdges,
  interGroupImports,
  intraGroupDensity,
  patternMatches,
  fileLevelPatterns,
  deploymentTopology,
  dataPipeline,
  docCoverage,
  dependencyDirection,
  fileStats: { totalFileNodes: fileNodes.length, filesPerGroup, nodeTypeCounts },
  fileFanIn: fanIn,
  fileFanOut: fanOut,
};
fs.writeFileSync(outPath, JSON.stringify(output, null, 2));
console.log('OK. groups:', JSON.stringify(filesPerGroup), 'types:', JSON.stringify(nodeTypeCounts));
