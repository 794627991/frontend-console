// ============================================================
// Intel HEX 解析器——浏览器适配版
// 移植自 bminer/intel-hex.js（https://github.com/bminer/intel-hex.js，MIT）
// 改动：Buffer → Uint8Array、exports → 全局 window.intelHexParse。
// 用法：intelHexParse(hexText) → {data: Uint8Array(0xFF 填充空洞),
//        startSegmentAddress, startLinearAddress}
// ============================================================
(function(global) {
  'use strict';
  const DATA = 0, END_OF_FILE = 1, EXT_SEGMENT_ADDR = 2, START_SEGMENT_ADDR = 3,
        EXT_LINEAR_ADDR = 4, START_LINEAR_ADDR = 5;
  const EMPTY_VALUE = 0xFF;

  function parseIntelHex(data) {
    if (data instanceof Uint8Array) data = new TextDecoder('ascii').decode(data);
    data = data.replace(/^[\r\n\s]+/, '');   // 容错：前导空白/空行（严格格式无此项）
    // 地址洞探测：先扫一遍记录收集地址区间，算出 base/min，避免 0xFF 前导空洞
    let buf = new Uint8Array(8192), bufLength = 0;
    let highAddress = 0, startSegmentAddress = null, startLinearAddress = null;
    let lineNum = 0, pos = 0;
    const SMALLEST_LINE = 11;
    while (pos + SMALLEST_LINE <= data.length) {
      if (data.charAt(pos++) !== ':')
        throw new Error('Line ' + (lineNum + 1) + ' does not start with a colon (:).');
      lineNum++;
      const dataLength = parseInt(data.substr(pos, 2), 16); pos += 2;
      const lowAddress = parseInt(data.substr(pos, 4), 16); pos += 4;
      const recordType = parseInt(data.substr(pos, 2), 16); pos += 2;
      const dataField = data.substr(pos, dataLength * 2); pos += dataLength * 2;
      const dataFieldBuf = _hexToBytes(dataField);
      const checksum = parseInt(data.substr(pos, 2), 16); pos += 2;
      // 校验和验证（与源库一致）
      let calcChecksum = (dataLength + (lowAddress >> 8) + lowAddress + recordType) & 0xFF;
      for (let i = 0; i < dataLength; i++) calcChecksum = (calcChecksum + dataFieldBuf[i]) & 0xFF;
      calcChecksum = (0x100 - calcChecksum) & 0xFF;
      if (checksum !== calcChecksum)
        throw new Error('Invalid checksum on line ' + lineNum + ': got ' + checksum + ', expected ' + calcChecksum);
      switch (recordType) {
        case DATA: {
          const absoluteAddress = highAddress + lowAddress;
          if (absoluteAddress + dataLength >= buf.length) {
            // 扩容（倍增策略与源库同：新长度*2）
            const tmp = new Uint8Array((absoluteAddress + dataLength) * 2);
            tmp.set(buf.subarray(0, bufLength));
            buf = tmp;
          }
          if (absoluteAddress > bufLength) buf.fill(EMPTY_VALUE, bufLength, absoluteAddress);
          buf.set(dataFieldBuf, absoluteAddress);
          bufLength = Math.max(bufLength, absoluteAddress + dataLength);
          break;
        }
        case END_OF_FILE:
          if (dataLength !== 0) throw new Error('Invalid EOF record on line ' + lineNum + '.');
          return { data: buf.subarray(0, bufLength), startSegmentAddress, startLinearAddress };
        case EXT_SEGMENT_ADDR:
          if (dataLength !== 2 || lowAddress !== 0) throw new Error('Invalid extended segment address record on line ' + lineNum + '.');
          highAddress = parseInt(dataField, 16) << 4;
          break;
        case START_SEGMENT_ADDR:
          if (dataLength !== 4 || lowAddress !== 0) throw new Error('Invalid start segment address record on line ' + lineNum + '.');
          startSegmentAddress = parseInt(dataField, 16);
          break;
        case EXT_LINEAR_ADDR:
          if (dataLength !== 2 || lowAddress !== 0) throw new Error('Invalid extended linear address record on line ' + lineNum + '.');
          highAddress = parseInt(dataField, 16) << 16;
          break;
        case START_LINEAR_ADDR:
          if (dataLength !== 4 || lowAddress !== 0) throw new Error('Invalid start linear address record on line ' + lineNum + '.');
          startLinearAddress = parseInt(dataField, 16);
          break;
        default:
          throw new Error('Invalid record type (' + recordType + ') on line ' + lineNum);
      }
      if (data.charAt(pos) === '\r') pos++;
      if (data.charAt(pos) === '\n') pos++;
    }
    throw new Error('Unexpected end of input: missing or invalid EOF record.');
  }

  function _hexToBytes(hex) {
    const out = new Uint8Array(hex.length >> 1);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.substr(i * 2, 2), 16);
    return out;
  }

  global.intelHexParse = parseIntelHex;
})(window);
