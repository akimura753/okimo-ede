// okimo_sw.js — OKIMO 人接近ページのオフライン用 Service Worker
// ページ・MediaPipe の WASM・モデルを一度キャッシュし、以後は OKIMO(AP)接続でも動くようにする。
const CACHE="okimo-approach-v1";
const PRECACHE=["okimo_approach_wifi.html","okimo_count_wifi.html","yolov8n_int8.onnx"];
self.addEventListener("install",e=>{
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(PRECACHE)).catch(()=>{}));
});
self.addEventListener("activate",e=>{ e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch",e=>{
  const url=e.request.url;
  // Pico(192.168.4.1) への通信はキャッシュせず常にネットワーク
  if(url.includes("192.168.4.1")){ return; }
  // それ以外（ページ・jsdelivr の WASM/JS・googleapis のモデル）はキャッシュ優先＋取得後保存
  e.respondWith(
    caches.match(e.request).then(hit=>{
      if(hit) return hit;
      return fetch(e.request).then(res=>{
        try{
          if(res && res.status===200 && (url.startsWith("https://cdn.jsdelivr.net")||url.startsWith("https://storage.googleapis.com")||url.startsWith(self.location.origin))){
            const copy=res.clone(); caches.open(CACHE).then(c=>c.put(e.request,copy));
          }
        }catch(_){}
        return res;
      }).catch(()=>hit);
    })
  );
});
