/* Byfrost Social V9 creator studio. No external assets, image services or music catalogs. */
(() => {
  'use strict';
  const $ = (selector, root=document) => root.querySelector(selector);
  const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
  const quick = $('#bfQuickCreate'), studio = $('#bfStudio'), viewer = $('#bfPhotoLightbox');
  const form = $('#bfStudioForm'), input = $('#bfStudioFiles');
  const canvas = $('#bfStudioCanvas'), thumbs = $('#bfStudioThumbs');
  const status = $('#bfStudioStatus'), progress = $('#bfStudioProgress'), publish = $('#bfStudioPublish');
  const type = $('#bfStudioType'), duration = $('#bfStudioDuration');
  const filter = $('#bfStudioFilter'), photoText = $('#bfStudioPhotoText');
  const textColor = $('#bfStudioTextColor'), textPosition = $('#bfStudioTextPosition');
  const audio = $('#bfStudioAudio'), audioPreview = $('#bfStudioAudioPreview');
  const video = $('#bfStudioVideo'), videoPreview = $('#bfStudioVideoPreview');
  const rights = $('#bfStudioRights');
  const MB = 1024 * 1024, MAX_POST = 15, MAX_CHAT = 5;
  const jobs = [];
  let selected = 0, sending = false, audioUrl = null, videoUrl = null;
  const fmt = n => (n/MB).toFixed(1)+' MB';
  const filters = {
    none:'none',vivid:'saturate(1.48) contrast(1.12)',warm:'sepia(.24) saturate(1.25)',
    cool:'hue-rotate(11deg) saturate(1.2)',mono:'grayscale(1) contrast(1.09)',
    soft:'contrast(.89) saturate(.92) brightness(1.05)'
  };
  const say = (message, kind='') => {if(!status)return;status.textContent=message;status.className='bf-upload-notice '+kind;};
  const open = dialog => {if(dialog && !dialog.open)dialog.showModal();};
  const close = dialog => {if(dialog?.open)dialog.close();};
  $$('[data-v9-open]').forEach(button => button.addEventListener('click', () => {
    if(button.dataset.v9Open === 'quick') open(quick);
    if(button.dataset.v9Open === 'studio') openStudio('post');
  }));
  $$('[data-v9-close]').forEach(button => button.addEventListener('click', () => close(button.closest('dialog'))));
  [quick,studio,viewer].filter(Boolean).forEach(dialog => dialog.addEventListener('click', e => {
    if(e.target===dialog && !sending)close(dialog);
  }));
  function openStudio(which='post'){
    close(quick);
    if(type)type.value=which;
    if(duration)duration.value=which==='story'?'24h':'permanent';
    if($('#bfStudioTitle'))$('#bfStudioTitle').textContent=which==='story'?'Create a temporary Story':'Create a feed post';
    if(publish)publish.textContent=which==='story'?'Publish Story ↗':'Publish post ↗';
    if(!jobs.length)drawEmpty();
    open(studio);
  }
  $$('[data-studio-type]').forEach(button=>button.addEventListener('click',()=>openStudio(button.dataset.studioType)));
  type?.addEventListener('change',()=>{
    if(type.value==='story' && duration.value==='permanent')duration.value='24h';
    if(publish)publish.textContent=type.value==='story'?'Publish Story ↗':'Publish post ↗';
  });
  const clearJobs = () => {jobs.forEach(j=>URL.revokeObjectURL(j.url));jobs.length=0;selected=0;};
  function drawEmpty(){
    if(!canvas)return;
    const ctx=canvas.getContext('2d');canvas.width=600;canvas.height=370;
    ctx.fillStyle='#22213a';ctx.fillRect(0,0,600,370);
    ctx.fillStyle='#b6a5fa';ctx.font='700 28px system-ui';ctx.textAlign='center';
    ctx.fillText('Your next story starts here ✦',300,178);
    ctx.font='15px system-ui';ctx.fillStyle='#dddded';
    ctx.fillText('Upload photos to preview, add filters and write on them',300,212);
  }
  function loadImage(job){return new Promise((resolve,reject)=>{
    const img=new Image(); img.onload=()=>resolve(img);img.onerror=()=>reject(new Error('Could not open '+job.file.name));img.src=job.url;
  });}
  function draw(canvasTarget, img, job, maxEdge){
    let width=img.naturalWidth, height=img.naturalHeight;
    const scale=Math.min(1,maxEdge/Math.max(width,height));
    width=Math.max(1,Math.round(width*scale)); height=Math.max(1,Math.round(height*scale));
    canvasTarget.width=width;canvasTarget.height=height;
    const ctx=canvasTarget.getContext('2d',{alpha:false});
    ctx.fillStyle='#fff';ctx.fillRect(0,0,width,height);
    ctx.filter=filters[job.filter]||'none';ctx.drawImage(img,0,0,width,height);ctx.filter='none';
    if(job.text){
      const fontSize=Math.max(18,Math.round(width*.055));
      ctx.font=`800 ${fontSize}px system-ui, sans-serif`;
      ctx.textAlign='center';ctx.textBaseline='middle';
      ctx.fillStyle=job.color;ctx.shadowColor='#000b';ctx.shadowBlur=fontSize*.25;
      ctx.lineWidth=Math.max(3,fontSize*.10);ctx.strokeStyle='#15141ccc';
      const maxWidth=width*.86;
      const words=job.text.split(/\s+/).filter(Boolean);
      const lines=[];let line='';
      for(const word of words){const test=line?line+' '+word:word;
        if(ctx.measureText(test).width>maxWidth && line){lines.push(line);line=word;}else line=test;
      }
      if(line)lines.push(line);
      const top=job.position==='top'?height*.17:job.position==='bottom'?height*.78:height*.5;
      lines.slice(0,4).forEach((value,index)=>{
        const y=top+(index-(Math.min(lines.length,4)-1)/2)*fontSize*1.3;
        ctx.strokeText(value,width/2,y,maxWidth);ctx.fillText(value,width/2,y,maxWidth);
      });
      ctx.shadowBlur=0;
    }
  }
  async function preview(){
    if(!jobs.length){drawEmpty();return;}
    const job=jobs[selected];
    filter.value=job.filter;photoText.value=job.text;textColor.value=job.color;textPosition.value=job.position;
    const key=job.url;
    try{
      const img=await loadImage(job);
      if(jobs[selected]?.url===key)draw(canvas,img,job,660);
    }catch(error){say(error.message,'error');}
  }
  function renderThumbs(){
    if(!thumbs)return;thumbs.replaceChildren();
    jobs.forEach((job,i)=>{
      const button=document.createElement('button');button.type='button';
      button.setAttribute('aria-pressed',String(i===selected));button.title='Edit photo '+(i+1);
      const img=document.createElement('img');img.src=job.url;img.alt='Photo '+(i+1);
      const small=document.createElement('small');small.textContent=i+1;
      button.append(img,small);button.addEventListener('click',()=>{selected=i;renderThumbs();preview();});
      thumbs.append(button);
    });
  }
  $('#bfStudioRemove')?.addEventListener('click',()=>{if(!jobs.length)return;URL.revokeObjectURL(jobs[selected].url);jobs.splice(selected,1);selected=Math.max(0,Math.min(selected,jobs.length-1));renderThumbs();preview();say(`${jobs.length}/15 photos ready.`);});
  input?.addEventListener('change',()=>{
    const files=[...input.files];
    if(!files.length)return;
    if(jobs.length+files.length>MAX_POST){say('You can add up to 15 photos per publication.','error');input.value='';return;}
    if(files.some(f=>!/^image\/(jpeg|png|webp)$/.test(f.type))){say('Use JPG, PNG or WebP photos only.','error');input.value='';return;}
    files.forEach(file=>jobs.push({file,url:URL.createObjectURL(file),filter:'none',text:'',color:'#ffffff',position:'middle'}));
    selected=jobs.length-files.length;
    renderThumbs();preview();
    const total=jobs.reduce((sum,job)=>sum+job.file.size,0);
    say(`${jobs.length}/15 photos · original ${fmt(total)}. ${files.some(f=>f.size>2*MB)?'Some photos exceed 2 MB; this is only an optimization warning, not a rejection.':''}`,
        files.some(f=>f.size>2*MB)?'warn':'');
    input.value='';
  });
  [[filter,'filter'],[photoText,'text'],[textColor,'color'],[textPosition,'position']].forEach(([field,key])=>{
    field?.addEventListener('input',()=>{if(!jobs.length)return;jobs[selected][key]=field.value;preview();});
  });
  video?.addEventListener('change',()=>{
    if(videoUrl){URL.revokeObjectURL(videoUrl);videoUrl=null;}
    videoPreview?.replaceChildren();
    const file=video.files?.[0];
    if(!file){if(videoPreview)videoPreview.textContent='Choose an MP4 or WebM video to preview before publishing.';return;}
    if(file.size>64*MB){say('Video exceeds 64 MB. Compress or shorten it before uploading.','error');video.value='';return;}
    if(!['video/mp4','video/webm'].includes(file.type)){
       say('Only MP4 or WebM videos are supported.','error');video.value='';return;}
    videoUrl=URL.createObjectURL(file);
    const player=document.createElement('video');player.controls=true;player.preload='metadata';player.playsInline=true;
    player.src=videoUrl;player.style.cssText='width:100%;max-height:260px;object-fit:contain;background:#15172c;border-radius:13px;';
    videoPreview?.append(player);
    const note=document.createElement('small');note.textContent=`${file.name} · ${fmt(file.size)} — original video will be uploaded.`;
    videoPreview?.append(note);
    say(file.size>25*MB?'Large video selected. Your host may impose an upload limit smaller than 64 MB.':'Video ready to publish.', file.size>25*MB?'warn':'');
  });
  audio?.addEventListener('change',()=>{
    if(audioUrl){URL.revokeObjectURL(audioUrl);audioUrl=null;}
    audioPreview?.replaceChildren();
    const file=audio.files?.[0];if(!file)return;
    if(file.size>12*MB){say('Audio exceeds 12 MB. Choose a shorter MP3/OGG/WAV file.','error');return;}
    audioUrl=URL.createObjectURL(file);
    const player=document.createElement('audio');player.controls=true;player.src=audioUrl;player.preload='none';player.style.maxWidth='100%';
    audioPreview.append(player);
  });
  async function encode(job, i){
    const img=await loadImage(job), output=document.createElement('canvas');
    draw(output,img,job,4096); // Do not downscale already valid 4K images.
    let blob=null;
    for(const quality of [.86,.79,.72]){
      blob=await new Promise(resolve=>output.toBlob(resolve,'image/jpeg',quality));
      if(!blob)throw new Error('Could not prepare photo '+(i+1));
      if(blob.size<=2*MB)break;
    }
    output.width=output.height=1; // free large backing memory after each photo
    return {file:new File([blob],`byfrost-photo-${i+1}.jpg`,{type:'image/jpeg'}),before:job.file.size,after:blob.size};
  }
  form?.addEventListener('submit',async event=>{
    event.preventDefault();if(sending)return;
    const ownAudio=audio.files?.[0];
    if(ownAudio && (!rights.checked || ownAudio.size>12*MB)){
      say('Confirm you own or have permission for the audio and keep it under 12 MB.','error');return;
    }
    if(!jobs.length && !ownAudio && !video?.files?.length && !form.elements.body.value.trim()){
      say('Write a caption or add photos, a video or authorized audio.','error');return;
    }
    if(type.value==='story' && duration.value==='permanent')duration.value='24h';
    sending=true;publish.disabled=true;progress.hidden=false;
    const bar=$('progress',progress),label=$('#bfStudioProgressText');bar.value=0;
    const payload=new FormData(form);payload.delete('photos');
    try{
      let finalSize=0,rawSize=0;
      for(let i=0;i<jobs.length;i++){
        label.textContent=`Preparing photo ${i+1} of ${jobs.length}…`;
        const result=await encode(jobs[i],i);
        payload.append('photos',result.file,result.file.name);
        finalSize+=result.after;rawSize+=result.before;
        // Yield between large canvases so the progress UI can paint.
        await new Promise(resolve=>setTimeout(resolve,0));
      }
      if(finalSize>0)say(`Photos prepared: ${fmt(rawSize)} → ${fmt(finalSize)}. Your 4K dimensions have been preserved where possible.`,finalSize>25*MB?'warn':'');
      const movie=video?.files?.[0];
      if(movie && movie.size>64*MB)throw Error('Video exceeds the 64 MB limit.');
      let totalUpload=0;for(const [,v] of payload.entries()){if(v instanceof File)totalUpload+=v.size;}
      if(totalUpload>158*MB)throw Error('Total upload exceeds the server limit of 160 MB. Reduce the photos or video.');
      label.textContent='Uploading securely…';
      await new Promise((resolve,reject)=>{
        const xhr=new XMLHttpRequest();xhr.open('POST',form.action,true);
        xhr.upload.addEventListener('progress',e=>{
          if(e.lengthComputable){const pct=Math.round(100*e.loaded/e.total);bar.value=pct;label.textContent='Uploading '+pct+'% ('+fmt(e.loaded)+' of '+fmt(e.total)+')';}
        });
        xhr.addEventListener('load',()=>{
          if(xhr.status>=200 && xhr.status<300){resolve(xhr.responseURL||'/app/?tab=home');}
          else reject(new Error(xhr.status===413?'Upload exceeds the current server or hosting limit. Try fewer photos.':`Upload failed (HTTP ${xhr.status}).`));
        });
        xhr.addEventListener('error',()=>reject(new Error('Network connection lost. Your local photo selection is still here.')));
        xhr.addEventListener('timeout',()=>reject(new Error('Upload timed out. Try fewer photos or a better connection.')));
        xhr.timeout=180000;
        xhr.send(payload);
        xhr.addEventListener('loadend',()=>{
          if(xhr.status>=200 && xhr.status<300){window.location.href=xhr.responseURL||'/app/?tab=home';}
        });
      });
    }catch(error){say(error.message,'error');label.textContent='Upload did not complete.';}
    finally{sending=false;publish.disabled=false;}
  });
  // Other photo inputs: warn at 2 MB, not an arbitrary upload blockade.
  $$('.photo-upload input[type=file]').forEach(el=>el.addEventListener('change',()=>{
    if(el.files.length>15){alert('Choose up to 15 photos.');el.value='';return;}
    if([...el.files].some(file=>file.size>2*MB)){
      const note=el.closest('.social-compose')?.querySelector('.compose-photo-name');
      if(note)note.textContent=`${el.files.length} photos — some over 2 MB. Consider Photo studio to optimize uploads.`;
    }
  }));
  // Attach multiple photos in chat, preview thumbnails, and never expose them publicly.
  $$('.bf-chat-compose input[type=file], #newMessageDialog input[type=file]').forEach(el=>{
    let urls=[];
    el.addEventListener('change',()=>{
      urls.forEach(URL.revokeObjectURL);urls=[];
      const files=[...el.files];
      if(files.length>MAX_CHAT){alert('Choose up to 5 photos for a private message.');el.value='';return;}
      const target=el.closest('form')?.querySelector('.bf-chat-file-previews');
      if(target){target.replaceChildren();for(const file of files){const url=URL.createObjectURL(file);urls.push(url);
        const img=document.createElement('img');img.src=url;img.alt=file.name;target.append(img);
      }}
      const label=el.closest('form')?.querySelector('.bf-attachment-label');
      if(label)label.textContent=files.length?`${files.length} photo(s) ${files.some(f=>f.size>2*MB)?'· over 2 MB will be optimized by server':''}`:'';
    });
  });
  // Private-message photo lightbox, with normal authenticated image URLs.
  document.addEventListener('click',event=>{
    const target=event.target.closest?.('[data-v9-lightbox]');
    if(!target || !viewer)return;
    const img=$('#bfLightboxImage');img.src=target.dataset.v9Lightbox;
    open(viewer);
  });
  // Locate and filter the *collection-point list* without disclosing current location.
  const mapSearch=$('#bfMapSearch');
  mapSearch?.addEventListener('input',()=>{
    const query=mapSearch.value.toLowerCase().trim();
    $$('[data-point-search]').forEach(item=>{item.hidden=!!query&&!item.dataset.pointSearch.includes(query);});
  });
  drawEmpty();
})();
