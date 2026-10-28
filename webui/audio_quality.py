"""Conservative technical checks; these do not judge voice timbre."""
import numpy as np
import soundfile as sf


def inspect_audio(path):
    audio,rate=sf.read(path,dtype='float32',always_2d=True)
    if not len(audio) or not np.isfinite(audio).all():return ['音频为空或含异常数值，请重新生成。']
    peak=float(np.max(np.abs(audio)));rms=float(np.sqrt(np.mean(audio.astype('float64')**2)))
    clipped=float(np.mean(np.abs(audio)>=.999))
    messages=[]
    if rms<.001:messages.append('音频音量极低或接近静音，请试听。')
    if clipped>.001:messages.append('音频存在较多削波，可能有失真，请试听。')
    return messages


def compare_segment_levels(paths):
    """Flag adjacent RMS differences as listening cues, not quality scores."""
    levels=[]
    for path in paths:
        audio,_=sf.read(path,dtype='float32',always_2d=True)
        rms=float(np.sqrt(np.mean(audio.astype('float64')**2))) if audio.size else 0
        levels.append(rms)
    warnings=[]
    for index,(left,right) in enumerate(zip(levels,levels[1:])):
        if min(left,right)>0.001 and max(left,right)/min(left,right)>2:
            warnings.append(f'第 {index+1} 与第 {index+2} 段音量差异较大，请试听衔接。')
    return warnings


def gentle_highpass(audio,rate):
    # Optional 70 Hz high-pass only; not a cure for a raspy or hollow voice.
    from scipy.signal import butter,sosfilt
    return sosfilt(butter(2,70,fs=rate,btype='highpass',output='sos'),audio).astype('float32')
