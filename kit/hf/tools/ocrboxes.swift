// ocrboxes: on-device text recognition (Apple Vision) -> JSON lines {text, conf, x, y, w, h} in image pixels (top-left origin).
//   swiftc -O -o kit/bin/ocrboxes kit/hf/tools/ocrboxes.swift
//   kit/bin/ocrboxes frame.png [--fast]
import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 2, let img = NSImage(contentsOfFile: args[1]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
  FileHandle.standardError.write("usage: ocrboxes <image> [--fast]\n".data(using: .utf8)!); exit(2)
}
let W = Double(cg.width), H = Double(cg.height)
let req = VNRecognizeTextRequest()
req.recognitionLevel = args.contains("--fast") ? .fast : .accurate
req.usesLanguageCorrection = false
try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
for obs in req.results ?? [] {
  guard let cand = obs.topCandidates(1).first else { continue }
  // word-level boxes for each word in the line, plus the line itself
  let text = cand.string
  var words: [[String: Any]] = []
  text.enumerateSubstrings(in: text.startIndex..<text.endIndex, options: .byWords) { sub, range, _, _ in
    if let sub = sub, let b = try? cand.boundingBox(for: range) {
      let r = b.boundingBox
      words.append(["text": sub, "x": Int(r.minX * W), "y": Int((1 - r.maxY) * H), "w": Int(r.width * W), "h": Int(r.height * H)])
    }
  }
  let r = obs.boundingBox
  let line: [String: Any] = ["text": text, "conf": Double(cand.confidence), "x": Int(r.minX * W), "y": Int((1 - r.maxY) * H),
                             "w": Int(r.width * W), "h": Int(r.height * H), "words": words]
  if let d = try? JSONSerialization.data(withJSONObject: line), let s = String(data: d, encoding: .utf8) { print(s) }
}
