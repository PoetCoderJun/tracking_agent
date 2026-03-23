#!/usr/bin/env python3
"""调试脚本用于测试 tracking-robot-stream"""
from __future__ import annotations

import sys
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scaffold.cli.run_robot_stream import (
    parse_args,
    _load_yolo,
    _load_cv2,
    normalize_source,
    is_camera_source,
    probe_video_fps,
    _video_frame_step,
    _track_kwargs,
    _results_for_video_file,
    VIDEO_TRACK_FPS,
)

def test_basic_setup():
    """测试基本设置"""
    print("=== Testing basic setup ===")
    
    # 测试参数
    test_args = [
        '--source', 'test_data/demo_video.mp4',
        '--text', '跟踪穿黑衣服的人',
        '--device', 'cpu',
        '--tracker', 'bytetrack.yaml',
        '--session-id', 'test_session_001',
        '--max-events', '1',
    ]
    
    sys.argv = ['test'] + test_args
    args = parse_args()
    print(f"Source: {args.source}")
    print(f"Text: {args.text}")
    print(f"Device: {args.device}")
    print(f"Tracker: {args.tracker}")
    print(f"Session ID: {args.session_id}")
    print(f"Max events: {args.max_events}")
    print("Args parsed OK")
    return args

def test_model_loading():
    """测试模型加载"""
    print("\n=== Testing model loading ===")
    YOLO = _load_yolo()
    print("YOLO loaded OK")
    model = YOLO('yolov8m.pt')
    print(f"Model initialized OK, task: {model.task}")
    return model

def test_video_info(args):
    """测试视频信息"""
    print("\n=== Testing video info ===")
    source = normalize_source(args.source)
    print(f"Normalized source: {source}")
    print(f"Is camera: {is_camera_source(source)}")
    
    video_path = Path(str(source))
    fps = probe_video_fps(video_path)
    print(f"Video FPS: {fps}")
    
    step = _video_frame_step(fps=fps, vid_stride=args.vid_stride)
    print(f"Frame step: {step}")
    
    return fps

def test_frame_processing(model, args, fps):
    """测试帧处理"""
    print("\n=== Testing frame processing ===")
    
    cv2 = _load_cv2()
    video_path = Path(str(args.source))
    
    # 打开视频
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video: {video_path}")
    
    # 读取第一帧
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError("Failed to read first frame")
    
    print(f"Frame shape: {frame.shape}")
    capture.release()
    
    # 测试跟踪
    print("Testing tracking on first frame...")
    kwargs = _track_kwargs(
        source=frame,
        args=args,
        stream=False,
        persist=True,
    )
    print(f"Track kwargs: {kwargs}")
    
    results = model.track(**kwargs)
    if results:
        result = results[0]
        print(f"Result boxes: {result.boxes}")
        if result.boxes is not None:
            print(f"Number of detections: {len(result.boxes)}")
            if result.boxes.id is not None:
                print(f"Track IDs: {result.boxes.id.tolist()}")
    else:
        print("No results")
    
    print("Frame processing OK")

def test_results_stream(model, args, fps):
    """测试结果流"""
    print("\n=== Testing results stream ===")
    
    video_path = Path(str(args.source))
    result_stream = _results_for_video_file(
        model=model,
        video_path=video_path,
        fps=fps,
        args=args,
    )
    
    # 获取第一个结果
    try:
        frame_index, result = next(result_stream)
        print(f"Frame index: {frame_index}")
        print(f"Result boxes: {result.boxes}")
        if result.boxes is not None:
            print(f"Number of detections: {len(result.boxes)}")
            if result.boxes.id is not None:
                print(f"Track IDs: {result.boxes.id.tolist()}")
        print("Results stream OK")
    except StopIteration:
        print("No frames in stream!")
    except Exception as e:
        print(f"Error in results stream: {e}")
        raise

def main():
    try:
        args = test_basic_setup()
        model = test_model_loading()
        fps = test_video_info(args)
        test_frame_processing(model, args, fps)
        test_results_stream(model, args, fps)
        print("\n=== All tests passed! ===")
        return 0
    except Exception as e:
        print(f"\n=== Test failed: {e} ===")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
