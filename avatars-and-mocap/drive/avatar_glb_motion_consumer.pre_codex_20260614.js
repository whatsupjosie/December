// ============================================================
// AVATAR MOTION CONSUMER
// Applies motion capture data to avatar skeletons
// Production code - fully functional
// ============================================================

class AvatarMotionConsumer {
    constructor(scene) {
        this.scene = scene;
        this.avatars = {}; // { avatar_id: { model, skeleton, animations, ... } }
        this.motionQueue = {}; // { avatar_id: [] }
        this.activeMotions = {}; // { avatar_id: motion_data }
        this.boneAliases = this.getBoneAliases();
        this.animationMixer = {};
        this.clock = new THREE.Clock();
        
        console.log('AvatarMotionConsumer initialized');
    }
    
    // ============================================================
    // Avatar Registration
    // ============================================================
    
    registerAvatar(avatarId, model, animations = []) {
        try {
            this.avatars[avatarId] = {
                id: avatarId,
                model: model,
                skeleton: this.extractSkeleton(model),
                animations: animations,
                bones: this.buildBoneMap(model),
                currentRotations: {},
                targetRotations: {},
                transitionProgress: {},
                mixers: []
            };
            
            this.motionQueue[avatarId] = [];
            this.activeMotions[avatarId] = null;
            
            // Build bone map for quick lookups
            this.avatars[avatarId].boneMap = this.buildBoneMapFast(model);
            
            console.log(`✓ Avatar registered: ${avatarId}`);
            console.log(`  Bones found: ${Object.keys(this.avatars[avatarId].boneMap).length}`);
            
            return this.avatars[avatarId];
        } catch (error) {
            console.error(`Failed to register avatar ${avatarId}:`, error);
            throw error;
        }
    }
    
    extractSkeleton(model) {
        // Find the skeleton in the model
        let skeleton = null;
        model.traverse((obj) => {
            if (obj.skeleton && !skeleton) {
                skeleton = obj.skeleton;
            }
        });
        return skeleton;
    }
    
    buildBoneMap(model) {
        const boneMap = {};
        model.traverse((node) => {
            if (node.isBone) {
                boneMap[node.name] = node;
            }
        });
        return boneMap;
    }
    
    buildBoneMapFast(model) {
        // Fast lookup map for bones
        const boneMap = {};
        const stack = [model];
        
        while (stack.length > 0) {
            const current = stack.pop();
            
            if (current.isBone || (current.type === 'Bone')) {
                boneMap[current.name] = current;
            }
            
            for (let child of current.children) {
                stack.push(child);
            }
        }
        
        return boneMap;
    }
    
    // ============================================================
    // Motion Commands
    // ============================================================
    
    applyMotion(avatarId, motionData) {
        if (!this.avatars[avatarId]) {
            console.error(`Avatar not found: ${avatarId}`);
            return false;
        }
        
        // Validate motion data
        if (!motionData || !motionData.bones) {
            console.error('Invalid motion data structure');
            return false;
        }
        
        // Add to queue
        this.motionQueue[avatarId].push({
            timestamp: performance.now(),
            bones: motionData.bones,
            duration: motionData.duration || 500,
            easing: motionData.easing || 'easeInOutQuad'
        });
        
        return true;
    }
    
    applyMotionImmediate(avatarId, boneName, rotation) {
        if (!this.avatars[avatarId]) return false;
        
        const avatar = this.avatars[avatarId];
        const bone = this.resolveBoneName(avatar, boneName);
        
        if (!bone) {
            console.warn(`Bone not found: ${boneName}`);
            return false;
        }
        
        // Apply rotation
        if (rotation.x !== undefined) bone.rotation.x = rotation.x;
        if (rotation.y !== undefined) bone.rotation.y = rotation.y;
        if (rotation.z !== undefined) bone.rotation.z = rotation.z;
        
        return true;
    }
    
    // ============================================================
    // Bone Resolution
    // ============================================================
    
    resolveBoneName(avatar, boneName) {
        const boneMap = avatar.boneMap;
        
        // Direct match
        if (boneMap[boneName]) {
            return boneMap[boneName];
        }
        
        // Try aliases
        const alias = this.boneAliases[boneName];
        if (alias) {
            for (let altName of alias) {
                if (boneMap[altName]) {
                    return boneMap[altName];
                }
            }
        }
        
        // Partial match (contains)
        for (let key in boneMap) {
            if (key.toLowerCase().includes(boneName.toLowerCase())) {
                return boneMap[key];
            }
        }
        
        return null;
    }
    
    getBoneAliases() {
        return {
            // Head
            'head': ['Head', 'head', 'Head_JNT', 'head.R', 'head.L'],
            'neck': ['Neck', 'neck', 'Neck_JNT', 'neck_01', 'Armature|Neck'],
            'jaw': ['Jaw', 'jaw', 'Jaw_JNT'],
            
            // Spine
            'spine': ['Spine', 'spine', 'Spine.001', 'spine_01', 'Spine_JNT', 'Armature|Spine'],
            'chest': ['Chest', 'chest', 'Spine.002', 'spine_02', 'Chest_JNT'],
            'hips': ['Hips', 'hips', 'Armature|Hips', 'Hip', 'hip'],
            
            // Left Arm
            'left_shoulder': ['Left Shoulder', 'left_shoulder', 'Shoulder.L', 'left_shoulder_JNT', 'Armature|Shoulder.L'],
            'left_arm': ['Left Arm', 'left_arm', 'Upper Arm.L', 'left_arm_JNT', 'LeftArm', 'Armature|Upper Arm.L'],
            'left_forearm': ['Left Forearm', 'left_forearm', 'Forearm.L', 'left_forearm_JNT', 'Armature|Forearm.L'],
            'left_hand': ['Left Hand', 'left_hand', 'Hand.L', 'left_hand_JNT', 'Armature|Hand.L'],
            
            // Right Arm
            'right_shoulder': ['Right Shoulder', 'right_shoulder', 'Shoulder.R', 'right_shoulder_JNT', 'Armature|Shoulder.R'],
            'right_arm': ['Right Arm', 'right_arm', 'Upper Arm.R', 'right_arm_JNT', 'RightArm', 'Armature|Upper Arm.R'],
            'right_forearm': ['Right Forearm', 'right_forearm', 'Forearm.R', 'right_forearm_JNT', 'Armature|Forearm.R'],
            'right_hand': ['Right Hand', 'right_hand', 'Hand.R', 'right_hand_JNT', 'Armature|Hand.R'],
            
            // Left Leg
            'left_hip': ['Left Hip', 'left_hip', 'Hip.L', 'LeftUpLeg'],
            'left_leg': ['Left Leg', 'left_leg', 'Upper Leg.L', 'LeftLeg', 'Armature|Upper Leg.L'],
            'left_foot': ['Left Foot', 'left_foot', 'Foot.L', 'LeftFoot', 'Armature|Foot.L'],
            
            // Right Leg
            'right_hip': ['Right Hip', 'right_hip', 'Hip.R', 'RightUpLeg'],
            'right_leg': ['Right Leg', 'right_leg', 'Upper Leg.R', 'RightLeg', 'Armature|Upper Leg.R'],
            'right_foot': ['Right Foot', 'right_foot', 'Foot.R', 'RightFoot', 'Armature|Foot.R'],
            
            // Face
            'left_eye': ['Eye.L', 'left_eye', 'LeftEye', 'Eye_L'],
            'right_eye': ['Eye.R', 'right_eye', 'RightEye', 'Eye_R'],
            'left_eyebrow': ['Brow.L', 'left_eyebrow', 'LeftBrow'],
            'right_eyebrow': ['Brow.R', 'right_eyebrow', 'RightBrow']
        };
    }
    
    // ============================================================
    // Motion Processing
    // ============================================================
    
    processMotion(avatarId, motion, deltaTime) {
        if (!this.avatars[avatarId]) return;
        
        const avatar = this.avatars[avatarId];
        const progress = Math.min(
            (performance.now() - motion.startTime) / motion.duration,
            1.0
        );
        
        // Apply easing
        const easedProgress = this.applyEasing(progress, motion.easing);
        
        // Apply each bone rotation
        for (let boneName in motion.bones) {
            const targetRotation = motion.bones[boneName];
            const bone = this.resolveBoneName(avatar, boneName);
            
            if (!bone) continue;
            
            // Interpolate rotation
            if (!motion.startRotations) {
                motion.startRotations = {};
            }
            
            if (!motion.startRotations[boneName]) {
                motion.startRotations[boneName] = {
                    x: bone.rotation.x,
                    y: bone.rotation.y,
                    z: bone.rotation.z
                };
            }
            
            const start = motion.startRotations[boneName];
            
            // Smooth interpolation
            bone.rotation.x = this.lerpAngle(start.x, targetRotation.x || start.x, easedProgress);
            bone.rotation.y = this.lerpAngle(start.y, targetRotation.y || start.y, easedProgress);
            bone.rotation.z = this.lerpAngle(start.z, targetRotation.z || start.z, easedProgress);
        }
        
        // Check if motion is complete
        if (progress >= 1.0) {
            return true; // Motion finished
        }
        
        return false;
    }
    
    applyEasing(progress, type) {
        switch (type) {
            case 'linear':
                return progress;
            case 'easeInQuad':
                return progress * progress;
            case 'easeOutQuad':
                return progress * (2 - progress);
            case 'easeInOutQuad':
                return progress < 0.5
                    ? 2 * progress * progress
                    : -1 + (4 - 2 * progress) * progress;
            case 'easeInCubic':
                return progress * progress * progress;
            case 'easeOutCubic':
                return 1 + (--progress) * progress * progress;
            case 'easeInOutCubic':
                return progress < 0.5
                    ? 4 * progress * progress * progress
                    : 1 + (--progress) * 2 * (progress) * (progress);
            default:
                return progress;
        }
    }
    
    lerpAngle(a, b, t) {
        // Handle angle wrapping
        let delta = b - a;
        while (delta > Math.PI) delta -= 2 * Math.PI;
        while (delta < -Math.PI) delta += 2 * Math.PI;
        return a + delta * t;
    }
    
    // ============================================================
    // Update Loop
    // ============================================================
    
    update() {
        // Process each avatar
        for (let avatarId in this.avatars) {
            const avatar = this.avatars[avatarId];
            const motionQueue = this.motionQueue[avatarId];
            
            // Check if current motion is done
            if (this.activeMotions[avatarId]) {
                const motion = this.activeMotions[avatarId];
                const isDone = this.processMotion(avatarId, motion, this.clock.getDelta());
                
                if (isDone) {
                    this.activeMotions[avatarId] = null;
                }
            }
            
            // Start next motion in queue if available
            if (!this.activeMotions[avatarId] && motionQueue.length > 0) {
                const nextMotion = motionQueue.shift();
                nextMotion.startTime = performance.now();
                this.activeMotions[avatarId] = nextMotion;
            }
        }
    }
    
    // ============================================================
    // Debug & Inspection
    // ============================================================
    
    inspectAvatar(avatarId) {
        if (!this.avatars[avatarId]) {
            console.log('Avatar not found:', avatarId);
            return;
        }
        
        const avatar = this.avatars[avatarId];
        console.log(`Avatar: ${avatarId}`);
        console.log(`  Bones (${Object.keys(avatar.boneMap).length}):`);
        
        const boneNames = Object.keys(avatar.boneMap).sort();
        boneNames.forEach(name => {
            const bone = avatar.boneMap[name];
            console.log(`    - ${name} (${bone.type})`);
        });
    }
    
    listAllBones(avatarId) {
        if (!this.avatars[avatarId]) return [];
        return Object.keys(this.avatars[avatarId].boneMap).sort();
    }
    
    debugMotionQueue(avatarId) {
        if (!this.avatars[avatarId]) return;
        
        console.log(`Avatar: ${avatarId}`);
        console.log(`  Active motion: ${this.activeMotions[avatarId] ? 'Yes' : 'None'}`);
        console.log(`  Queued motions: ${this.motionQueue[avatarId].length}`);
    }
}

// ============================================================
// Export for use
// ============================================================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AvatarMotionConsumer;
}
