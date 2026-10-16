// 中文标签正则行为验证（u 模式 \p 转写后）
const re = /(\[\[[^\[\]\n]{1,120}\]\])|(#[\p{L}_][\p{L}\p{N}_]{0,39}?(?=$|[\s，。、；：！？（）【】《》「」"'`,;:!?.\-(){}[\]|*=+&%$@~^<>/]))/gu;
const t1 = '前缀 [[claude配置.note]] 中 #标签1 后 #fff #123 x';
const got = [];
let r;
while ((r = re.exec(t1))) got.push(r[0]);
console.log('zh/link:', JSON.stringify(got));
const t2 = '电机 #硬件调试 中文 [[链接甲]]';
const got2 = [];
while ((r = re.exec(t2))) got2.push(r[0]);
console.log('zh-only:', JSON.stringify(got2));
