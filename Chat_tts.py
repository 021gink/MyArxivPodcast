import os
import logging
from typing import List
import torch
import torchaudio
import ChatTTS
from pydub import AudioSegment
import json
import numpy as np
import config
import psutil
import os.path


os.environ['HF_ENDPOINT'] = "https://hf-mirror.com"

class TTSEngine:


#1.将文本分割成多个小段
    def _split_text(self, text):
        """Split long text into smaller segments, with special handling for Chinese text"""
        max_chars = 500
        parts = []
        
        # Use different split logic for Chinese text
        if any('\u4e00' <= char <= '\u9fff' for char in text):
            # Use Chinese punctuation marks for splitting
            separators = ['。', '！', '？', '；']
            current_part = ''
            
            for char in text:
                current_part += char
                if len(current_part) >= max_chars or (char in separators and current_part):
                    parts.append(current_part)
                    current_part = ''
            
            if current_part:
                parts.append(current_part)
        else:
            # Original English split logic
            sentences = text.split('.')
            current_part = []
            current_length = 0
            
            for sentence in sentences:
                sentence = sentence.strip() + '.'
                if current_length + len(sentence) <= max_chars:
                    current_part.append(sentence)
                    current_length += len(sentence)
                else:
                    if current_part:
                        parts.append(''.join(current_part))
                    current_part = [sentence]
                    current_length = len(sentence)
            
            if current_part:
                parts.append(''.join(current_part))
        
        return parts
#2.初始化chat与音色
    def _init_chat(self):
        self.chat = ChatTTS.Chat()
        self.chat.load(compile=False)

    def __init__(self, host_voice_path, guest_voice_path):
        if not host_voice_path or not guest_voice_path:
            raise ValueError("Host voice path and guest voice path must be provided and cannot be empty.")
        
        self.host_voice_path = host_voice_path
        self.guest_voice_path = guest_voice_path

        self._init_chat()
        if not os.path.exists('speakervoice'):
            os.makedirs('speakervoice')
        # 检查路径是否有效
        if not os.path.isfile(self.host_voice_path):
            host_spk = self.chat.sample_random_speaker()
            torch.save(host_spk, 'speakervoice/host_voice.pth')
           
        
        if not os.path.isfile(self.guest_voice_path):
            guest_spk = self.chat.sample_random_speaker()
            torch.save(guest_spk, 'speakervoice/guest_voice.pth')
            
#3.生成音频文件

    def convert_dialog(self, text, output_dir):
        """Convert dialogue text to multiple audio files and merge them"""
        dialog_parts = []
        current_speaker = None
        current_text = []
        
        # Support more dialogue marker formats
        host_markers = ['Host:', '主持人:', '主播:']
        guest_markers = ['Guest:', '嘉宾:', '客人:']
        
        for line in text.split('\n'):
            # 去除小标题
            if line.startswith('=== ') and line.endswith(' ==='):
                continue
            if any(line.startswith(marker) for marker in host_markers):
                if current_speaker:
                    dialog_parts.append((current_speaker, ''.join(current_text)))
                current_speaker = 'Host'
                # Remove all possible markers
                for marker in host_markers:
                    line = line.replace(marker, '')
                current_text = [line]
            elif any(line.startswith(marker) for marker in guest_markers):
                if current_speaker:
                    dialog_parts.append((current_speaker, ''.join(current_text)))
                current_speaker = 'Guest'
                # Remove all possible markers
                for marker in guest_markers:
                    line = line.replace(marker, '')
                current_text = [line]
            elif line.strip():
                if current_speaker:
                    current_text.append(line)
        
        if current_speaker and current_text:
            dialog_parts.append((current_speaker, ''.join(current_text)))

        # Generate audio for each dialogue part
        audio_files = []
        for i, (speaker, content) in enumerate(dialog_parts):
            content_parts = self._split_text(content)
            voice_configs = [
                            {
                                "oral": 1,            # 较低的语调
                                "laugh": 0,
                                "break": 4
                            },
                            {
                                "oral": 3,             # 较柔和的语调
                                "laugh": 0,
                                "break": 2
                            }
                            ]
            config = voice_configs[0] if speaker == 'Host' else voice_configs[1]
            rand_spk = torch.load(self.host_voice_path) if speaker == 'Host' else torch.load(self.guest_voice_path)

            for j, part in enumerate(content_parts):
                params_infer_code = ChatTTS.Chat.InferCodeParams(
                spk_emb=rand_spk,
                temperature=0.3,
                top_P=0.7,
                top_K=20
            )
                # 设置语音风格

                params_refine_text = ChatTTS.Chat.RefineTextParams(
                prompt=f'[oral_{config["oral"]}][laugh_{config["laugh"]}][break_{config["break"]}]'
                )
                wavs = self.chat.infer(part, params_refine_text=params_refine_text, params_infer_code=params_infer_code, use_decoder=True)
                
                temp_file = os.path.join(output_dir, f'part_{i}_{j}.wav')
                try:
                    torchaudio.save(temp_file, torch.from_numpy(wavs[0]).unsqueeze(0), 24000)
                except:
                    torchaudio.save(temp_file, torch.from_numpy(wavs[0]), 24000)
                audio_files.append(temp_file)
        return audio_files
#4.合并音频文件``
    def merge_audio_files(self, audio_files, output_path):
        """Merge multiple audio files"""
        try:
            combined = AudioSegment.empty()
            for audio_file in audio_files:
                segment = AudioSegment.from_wav(audio_file)
                combined += segment
                # Add brief pause
                combined += AudioSegment.silent(duration=500)  # Add 500ms pause
            
            # Export merged audio file
            combined.export(output_path, format="wav")
        
            # Delete temporary files
            for audio_file in audio_files:
                try:
                    os.remove(audio_file)
                except Exception as e:
                    print(f"Failed to delete temporary file: {e}")
            
            return output_path
        except Exception as e:
            raise Exception(f"Failed to merge audio files: {e}")